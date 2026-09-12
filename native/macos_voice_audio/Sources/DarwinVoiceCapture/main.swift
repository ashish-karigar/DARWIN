import AVFoundation
import Darwin
import Foundation

private let targetSampleRate = 16_000.0
private let targetFrameCount = 1_280

private func fail(_ message: String, code: Int32 = 1) -> Never {
    FileHandle.standardError.write(Data("darwin-voice-capture: \(message)\n".utf8))
    exit(code)
}

private final class PCMWriter: @unchecked Sendable {
    private let queue = DispatchQueue(label: "darwin.voice.capture.stdout")
    private var pending = Data()
    private var stopped = false

    func append(_ data: Data) {
        queue.async { [weak self] in
            guard let self, !self.stopped else { return }
            self.pending.append(data)
            let frameBytes = targetFrameCount * MemoryLayout<Int16>.size
            while self.pending.count >= frameBytes {
                let frame = self.pending.prefix(frameBytes)
                do {
                    try FileHandle.standardOutput.write(contentsOf: frame)
                } catch {
                    self.stopped = true
                    DispatchQueue.main.async { exit(0) }
                    return
                }
                self.pending.removeFirst(frameBytes)
            }
        }
    }

    func stop() {
        queue.sync { stopped = true }
    }
}

private final class VoiceCapture {
    private let engine = AVAudioEngine()
    private let writer = PCMWriter()
    private var converter: AVAudioConverter?
    private var converterInputFormat: AVAudioFormat?
    private var outputFormat: AVAudioFormat?

    func start() throws {
        let input = engine.inputNode
        let output = engine.outputNode

        // Apple requires the engine to be stopped while voice processing changes.
        try input.setVoiceProcessingEnabled(true)
        if !output.isVoiceProcessingEnabled {
            try output.setVoiceProcessingEnabled(true)
        }
        if #available(macOS 14.0, *) {
            input.voiceProcessingOtherAudioDuckingConfiguration = .init(
                enableAdvancedDucking: false,
                duckingLevel: .min
            )
        }

        let inputFormat = input.outputFormat(forBus: 0)
        guard inputFormat.sampleRate > 0, inputFormat.channelCount > 0 else {
            throw NSError(
                domain: "DarwinVoiceCapture",
                code: 2,
                userInfo: [NSLocalizedDescriptionKey: "No usable default microphone is available"]
            )
        }
        guard let converterInputFormat = AVAudioFormat(
            commonFormat: .pcmFormatFloat32,
            sampleRate: inputFormat.sampleRate,
            channels: 1,
            interleaved: false
        ), let outputFormat = AVAudioFormat(
            commonFormat: .pcmFormatFloat32,
            sampleRate: targetSampleRate,
            channels: 1,
            interleaved: false
        ), let converter = AVAudioConverter(
            from: converterInputFormat,
            to: outputFormat
        ) else {
            throw NSError(
                domain: "DarwinVoiceCapture",
                code: 3,
                userInfo: [NSLocalizedDescriptionKey: "Unable to configure 16 kHz mono conversion"]
            )
        }
        self.converterInputFormat = converterInputFormat
        self.outputFormat = outputFormat
        self.converter = converter

        input.installTap(onBus: 0, bufferSize: 960, format: inputFormat) {
            [weak self] buffer, _ in
            self?.convertAndWrite(buffer)
        }

        engine.prepare()
        try engine.start()
        let message = "darwin-voice-capture: ready; voice processing enabled; "
            + "input=\(Int(inputFormat.sampleRate))Hz/\(inputFormat.channelCount)ch "
            + "output=16000Hz/1ch\n"
        FileHandle.standardError.write(Data(message.utf8))
    }

    private func convertAndWrite(_ inputBuffer: AVAudioPCMBuffer) {
        guard let converter, let converterInputFormat, let outputFormat,
              let source = inputBuffer.floatChannelData?[0],
              let monoInput = AVAudioPCMBuffer(
                  pcmFormat: converterInputFormat,
                  frameCapacity: inputBuffer.frameLength
              ), let mono = monoInput.floatChannelData?[0] else { return }
        monoInput.frameLength = inputBuffer.frameLength
        mono.update(from: source, count: Int(inputBuffer.frameLength))
        let ratio = outputFormat.sampleRate / inputBuffer.format.sampleRate
        let capacity = AVAudioFrameCount(ceil(Double(inputBuffer.frameLength) * ratio) + 16)
        guard let outputBuffer = AVAudioPCMBuffer(
            pcmFormat: outputFormat,
            frameCapacity: capacity
        ) else { return }

        var supplied = false
        var conversionError: NSError?
        let status = converter.convert(to: outputBuffer, error: &conversionError) {
            _, outStatus in
            if supplied {
                outStatus.pointee = .noDataNow
                return nil
            }
            supplied = true
            outStatus.pointee = .haveData
            return monoInput
        }
        guard status != .error, conversionError == nil, outputBuffer.frameLength > 0 else {
            return
        }

        guard let samples = outputBuffer.floatChannelData?[0] else { return }
        let count = Int(outputBuffer.frameLength)
        var pcm = [Int16](repeating: 0, count: count)
        for index in 0..<count {
            let scaled = max(-1.0, min(1.0, samples[index])) * Float(Int16.max)
            pcm[index] = Int16(scaled.rounded())
        }
        writer.append(pcm.withUnsafeBytes { Data($0) })
    }

    func stop() {
        engine.inputNode.removeTap(onBus: 0)
        engine.stop()
        writer.stop()
    }
}

private let capture = VoiceCapture()
do {
    try capture.start()
} catch {
    fail(error.localizedDescription)
}

signal(SIGINT, SIG_IGN)
signal(SIGTERM, SIG_IGN)
private let signalSource = DispatchSource.makeSignalSource(signal: SIGTERM, queue: .main)
signalSource.setEventHandler {
    capture.stop()
    exit(0)
}
signalSource.resume()

dispatchMain()
