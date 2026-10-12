import { BrowserWindow } from 'electron'
import { execFile } from 'node:child_process'
import { cpus } from 'node:os'

type CpuSample = { idle: number; total: number }

const sampleCpu = (): CpuSample =>
  cpus().reduce(
    (sample, cpu) => {
      const total = Object.values(cpu.times).reduce((sum, value) => sum + value, 0)
      sample.idle += cpu.times.idle
      sample.total += total
      return sample
    },
    { idle: 0, total: 0 }
  )

const readBattery = (): Promise<number | null> =>
  new Promise((resolveBattery) => {
    if (process.platform !== 'darwin') return resolveBattery(null)
    execFile('/usr/bin/pmset', ['-g', 'batt'], { timeout: 2_000 }, (error, stdout) => {
      if (error) return resolveBattery(null)
      const match = stdout.match(/(\d+)%/)
      resolveBattery(match ? Number(match[1]) : null)
    })
  })

export const registerSystemStats = (window: BrowserWindow) => {
  let previous = sampleCpu()
  let battery: number | null = null
  let batteryReadAt = 0

  const publish = async () => {
    if (window.isDestroyed() || window.webContents.isDestroyed()) return
    const current = sampleCpu()
    const totalDelta = current.total - previous.total
    const idleDelta = current.idle - previous.idle
    previous = current
    if (Date.now() - batteryReadAt > 30_000) {
      batteryReadAt = Date.now()
      battery = await readBattery()
    }
    if (window.isDestroyed() || window.webContents.isDestroyed()) return
    window.webContents.send('system-stats:update', {
      cpu: totalDelta > 0 ? Math.round((1 - idleDelta / totalDelta) * 100) : 0,
      battery
    })
  }

  const timer = setInterval(() => void publish(), 2_000)
  window.webContents.once('did-finish-load', () => void publish())
  window.once('closed', () => clearInterval(timer))
}
