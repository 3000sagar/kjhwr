import { Component, type ErrorInfo, type ReactNode } from 'react'

interface Props {
  children: ReactNode
}

interface State {
  error: Error | null
}

export default class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null }

  static getDerivedStateFromError(error: Error): State {
    return { error }
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error('Dashboard render error', error, info.componentStack)
  }

  private reset = () => {
    this.setState({ error: null })
  }

  render() {
    if (this.state.error) {
      return (
        <main className="fatal-error" role="alert">
          <section className="global-error">
            <h1>Dashboard could not render</h1>
            <p>{this.state.error.message || 'An unexpected rendering error occurred.'}</p>
            <button type="button" onClick={this.reset}>Try again</button>
          </section>
        </main>
      )
    }

    return this.props.children
  }
}
