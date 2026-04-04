import { Component } from 'react';
import { AlertTriangle, RefreshCw } from 'lucide-react';

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
    this.props.onReset?.();
  };

  render() {
    if (this.state.hasError) {
      if (this.props.fallback) {
        return this.props.fallback({
          error: this.state.error,
          resetErrorBoundary: this.handleReset,
        });
      }

      return (
        <div style={{
          display: 'flex', flexDirection: 'column', alignItems: 'center',
          justifyContent: 'center', minHeight: '40vh', gap: '1rem',
          padding: '2rem', color: 'var(--text2, #555)',
        }}>
          <AlertTriangle size={48} color="var(--danger, #e74c3c)" />
          <h2 style={{ margin: 0 }}>오류가 발생했습니다</h2>
          <p style={{ margin: 0, color: 'var(--text3, #888)', textAlign: 'center', maxWidth: 400 }}>
            {this.props.message || '페이지를 표시하는 중 문제가 발생했습니다. 다시 시도해 주세요.'}
          </p>
          {import.meta.env.DEV && this.state.error && (
            <pre style={{
              background: 'var(--bg2, #f5f5f5)', padding: '0.75rem 1rem',
              borderRadius: 8, fontSize: '0.8rem', maxWidth: '100%',
              overflow: 'auto', whiteSpace: 'pre-wrap',
            }}>
              {this.state.error.message}
            </pre>
          )}
          <button
            onClick={this.handleReset}
            style={{
              display: 'inline-flex', alignItems: 'center', gap: '0.5rem',
              padding: '0.6rem 1.2rem', borderRadius: 8, border: 'none',
              background: 'var(--primary, #3b82f6)', color: '#fff',
              cursor: 'pointer', fontSize: '0.95rem',
            }}
          >
            <RefreshCw size={16} />
            다시 시도
          </button>
        </div>
      );
    }

    return this.props.children;
  }
}
