import React from 'react';

export default class ErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = { error: null };
  }

  static getDerivedStateFromError(error) {
    return { error };
  }

  componentDidCatch(error, info) {
    console.error('Render error caught by ErrorBoundary:', error, info);
  }

  render() {
    if (this.state.error) {
      return (
        <div style={{
          padding: '32px 24px',
          textAlign: 'center',
          margin: '24px',
          border: '1px solid #fca5a5',
          borderRadius: '12px',
          background: '#fff5f5',
        }}>
          <div style={{ fontSize: '20px', marginBottom: '8px' }}>⚠️</div>
          <div style={{ fontWeight: 600, fontSize: '15px', color: '#dc2626', marginBottom: '8px' }}>
            Something went wrong
          </div>
          <div style={{ fontSize: '13px', color: '#6b7280', marginBottom: '20px', maxWidth: '360px', margin: '0 auto 20px' }}>
            {this.state.error.message || 'An unexpected error occurred.'}
          </div>
          <button
            style={{
              padding: '8px 20px',
              border: '1px solid #d1d5db',
              borderRadius: '8px',
              background: '#fff',
              cursor: 'pointer',
              fontSize: '14px',
              fontWeight: 500,
            }}
            onClick={() => this.setState({ error: null })}
          >
            Try again
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}
