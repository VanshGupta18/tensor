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
      
      if (result && result.token) {
        localStorage.setItem('token', result.token);
      }
      onLoginSuccess(result.username || username);
    } catch (err) {
      setError(err.message || (isRegistering ? 'Registration failed' : 'Invalid credentials'));
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="login-page">
      <div className="login-container panel">
        <h2>{isRegistering ? 'Create Account' : 'Welcome back'}</h2>
        <p>{isRegistering ? 'Sign up for a new account' : 'Sign in to your account'}</p>

        {error && <div className="error-msg">{error}</div>}

        <form onSubmit={handleSubmit}>
          <div className="form-group">
            <label>Username</label>
            <input
              type="text"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              className="form-input"
              disabled={loading}
              required
            />
          </div>
          <div className="form-group">
            <label>Password</label>
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="form-input"
              disabled={loading}
              required
            />
          </div>
          <button type="submit" className="btn btn-primary" style={{ width: '100%', marginTop: '8px' }} disabled={loading}>
            {loading ? (isRegistering ? 'Registering…' : 'Signing in…') : (isRegistering ? 'Register' : 'Sign In')}
          </button>
        </form>
        <div style={{ marginTop: '16px', textAlign: 'center' }}>
          <button 
            type="button" 
            className="btn btn-ghost" 
            onClick={() => { setIsRegistering(!isRegistering); setError(''); }}
            disabled={loading}
          >
            {isRegistering ? 'Already have an account? Sign In' : 'Need an account? Register'}
          </button>
        </div>
      </div>
    </div>
  );
}
