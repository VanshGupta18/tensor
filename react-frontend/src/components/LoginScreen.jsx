import React, { useState } from 'react';
import { login, register } from '../api/authApi.js';

export default function LoginScreen({ onLoginSuccess }) {
  const [isRegistering, setIsRegistering] = useState(false);
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [error,    setError]    = useState('');
  const [loading,  setLoading]  = useState(false);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError('');
    setLoading(true);
    try {
      const result = isRegistering
        ? await register(username, password)
        : await login(username, password);
      if (result?.token) localStorage.setItem('token', result.token);
      onLoginSuccess(result.username || username);
    } catch (err) {
      setError(err.message || (isRegistering ? 'Registration failed' : 'Invalid credentials'));
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="login-page">
      <div className="login-card">

        {/* Left — brand + value props */}
        <div className="login-left">
          <div className="ll-brand">
            <div className="ll-mark">TF</div>
            <span className="ll-name">TenderFlow</span>
          </div>

          <div>
            <div className="ll-headline">
              Procurement,<br />made <em>precise</em>.
            </div>
            <div className="ll-sub">
              One workspace to track, review, and approve tenders — with an AI copilot that reads the PDFs for you.
            </div>
          </div>

          <div className="ll-feats" aria-hidden="true">
            <div className="ll-feat"><div className="ll-dot" />Upload a PDF — fields populate automatically</div>
            <div className="ll-feat"><div className="ll-dot" />Full version history and approval audit trail</div>
            <div className="ll-feat"><div className="ll-dot" />Ask the AI Copilot any question about a tender</div>
          </div>
        </div>

        {/* Right — form */}
        <div className="login-right">
          <div className="lr-title">
            {isRegistering ? 'Create account' : 'Welcome back'}
          </div>
          <div className="lr-sub">
            {isRegistering ? 'Sign up for a new account' : 'Sign in to continue'}
          </div>

          {error && <div className="error-msg">{error}</div>}

          <form onSubmit={handleSubmit}>
            <div className="login-field">
              <label htmlFor="lf-username">Username</label>
              <input
                className="login-input"
                type="text"
                id="lf-username"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                autoComplete="username"
                disabled={loading}
                required
                placeholder="your.name"
              />
            </div>
            <div className="login-field">
              <label htmlFor="lf-password">Password</label>
              <input
                className="login-input"
                type="password"
                id="lf-password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                autoComplete={isRegistering ? 'new-password' : 'current-password'}
                disabled={loading}
                required
                placeholder="••••••••"
              />
            </div>
            <button type="submit" className="login-submit" disabled={loading}>
              {loading
                ? (isRegistering ? 'Registering…' : 'Signing in…')
                : (isRegistering ? 'Register' : 'Sign In')}
            </button>
          </form>

          <div className="login-toggle">
            <button
              type="button"
              onClick={() => { setIsRegistering(!isRegistering); setError(''); }}
              disabled={loading}
            >
              {isRegistering
                ? 'Already have an account? Sign In'
                : 'Need an account? Register'}
            </button>
          </div>
        </div>

      </div>
    </div>
  );
}
