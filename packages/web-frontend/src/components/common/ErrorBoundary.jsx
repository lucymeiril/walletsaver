import { Component } from 'react';
import ErrorFallback from './ErrorFallback';

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
        return this.props.fallback;
      }
      return (
        <ErrorFallback
          error={this.state.error}
          message={this.props.fallbackMessage || '오류가 발생했습니다. 다시 시도해 주세요.'}
          onRetry={this.handleReset}
        />
      );
    }
    return this.props.children;
  }
}
