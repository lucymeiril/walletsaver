import { Component } from 'react';

/**
 * Top-level error boundary — catches render errors in child components
 * and shows a recoverable fallback UI instead of a blank screen.
 */
export default class ErrorBoundary extends Component {
  constructor(props) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error) {
    return { hasError: true, error };
  }

  componentDidCatch(error, errorInfo) {
    console.error('[ErrorBoundary]', error, errorInfo);
  }

  handleReset = () => {
    this.setState({ hasError: false, error: null });
  };

  render() {
    if (this.state.hasError) {
      if (this.props.fallback) {
        return this.props.fallback;
      }
      return (
        <div style={{
          display: 'flex', flexDirection: 'column', alignItems: 'center',
          justifyContent: 'center', minHeight: '200px', padding: '2rem',
          color: '#64748b',
        }}>
          <h2 style={{ marginBottom: '0.5rem', color: '#ef4444' }}>
            오류가 발생했습니다
          </h2>
          <p style={{ marginBottom: '1rem', textAlign: 'center' }}>
            페이지를 표시하는 중 문제가 발생했습니다.
          </p>
          <button
            onClick={this.handleReset}
            style={{
              padding: '0.5rem 1.5rem', borderRadius: '6px',
              border: '1px solid #e2e8f0', background: '#fff',
              cursor: 'pointer', fontSize: '0.875rem',
            }}
          >
            다시 시도
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}
