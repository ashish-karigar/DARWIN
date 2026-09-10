import { Component, type ErrorInfo, type ReactNode } from 'react'
import { Button } from '../../components/ui'

interface NativeAppErrorBoundaryProps {
  appName: string
  children: ReactNode
}

interface NativeAppErrorBoundaryState {
  error: Error | null
  recoveryKey: number
}

export class NativeAppErrorBoundary extends Component<
  NativeAppErrorBoundaryProps,
  NativeAppErrorBoundaryState
> {
  state: NativeAppErrorBoundaryState = { error: null, recoveryKey: 0 }

  static getDerivedStateFromError(error: Error): Partial<NativeAppErrorBoundaryState> {
    return { error }
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error(`DARWIN app crashed: ${this.props.appName}`, error, info.componentStack)
  }

  render() {
    if (this.state.error) {
      return (
        <div className="native-app-error" role="alert">
          <strong>{this.props.appName} stopped unexpectedly.</strong>
          <p>The rest of DARWIN is still running.</p>
          <Button
            size="small"
            onClick={() =>
              this.setState((state) => ({
                error: null,
                recoveryKey: state.recoveryKey + 1
              }))
            }
          >
            Reload app
          </Button>
        </div>
      )
    }

    return (
      <div key={this.state.recoveryKey} className="native-app-boundary">
        {this.props.children}
      </div>
    )
  }
}
