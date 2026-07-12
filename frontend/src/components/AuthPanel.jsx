import { useState } from 'react'
import { login, register } from '../api.js'

// Compact sign-in / sign-up modal. Accounts are OPTIONAL — this only unlocks
// cross-device tracker sync; the anonymous localStorage experience is unchanged.
// On success it hands the parent { token, email } to store and switch source.
export default function AuthPanel({ onClose, onAuthed }) {
  const [mode, setMode] = useState('login') // 'login' | 'register'
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  const isRegister = mode === 'register'

  async function submit(e) {
    e.preventDefault()
    setError('')
    setBusy(true)
    try {
      const fn = isRegister ? register : login
      const data = await fn(email.trim(), password)
      onAuthed(data) // { token, email }
    } catch (err) {
      setError(String(err.message || err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="modal" role="dialog" aria-modal="true" aria-label="Account">
      <div className="modal__backdrop" onClick={onClose} />
      <div className="modal__card">
        <div className="modal__head">
          <h2 className="modal__title">
            {isRegister ? 'Create an account' : 'Sign in'}
          </h2>
          <button
            type="button"
            className="modal__close"
            aria-label="Close"
            onClick={onClose}
          >
            ✕
          </button>
        </div>
        <p className="modal__sub">
          Optional — sign in to sync your tracker across devices. You can keep
          using ApplyLens without an account.
        </p>
        <form className="authform" onSubmit={submit}>
          <label className="field__label" htmlFor="auth-email">Email</label>
          <input
            id="auth-email"
            className="input"
            type="email"
            autoComplete="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="you@example.com"
            required
          />
          <label className="field__label" htmlFor="auth-password">Password</label>
          <input
            id="auth-password"
            className="input"
            type="password"
            autoComplete={isRegister ? 'new-password' : 'current-password'}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            placeholder={isRegister ? 'At least 6 characters' : 'Your password'}
            required
          />
          {error && (
            <div className="alert alert--error" role="alert">
              {error}
            </div>
          )}
          <button className="btn btn--primary" disabled={busy} type="submit">
            {busy && <span className="spinner" aria-hidden="true" />}
            {isRegister ? 'Create account' : 'Sign in'}
          </button>
        </form>
        <p className="modal__switch">
          {isRegister ? 'Already have an account?' : "Don't have an account?"}{' '}
          <button
            type="button"
            className="linkbtn"
            onClick={() => {
              setError('')
              setMode(isRegister ? 'login' : 'register')
            }}
          >
            {isRegister ? 'Sign in' : 'Create one'}
          </button>
        </p>
      </div>
    </div>
  )
}
