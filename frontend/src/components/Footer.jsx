import { useState } from 'react'

// Footer with an honest privacy summary + a modal for the full text.
export default function Footer() {
  const [open, setOpen] = useState(false)
  return (
    <footer className="footer">
      <p className="footer__line">
        Anonymous by default — your CV and analyses stay in your browser unless you sign in.{' '}
        <button type="button" className="linkbtn" onClick={() => setOpen(true)}>
          Privacy &amp; data
        </button>
      </p>
      <p className="footer__meta">ApplyLens — a personal project, provided as-is.</p>

      {open && (
        <div className="modal" role="dialog" aria-modal="true">
          <div className="modal__backdrop" onClick={() => setOpen(false)} />
          <div className="modal__card">
            <div className="modal__head">
              <h3 className="modal__title">Privacy &amp; data</h3>
              <button type="button" className="modal__close" aria-label="Close" onClick={() => setOpen(false)}>
                ✕
              </button>
            </div>
            <div className="privacy">
              <p>
                <strong>Anonymous by default.</strong> If you don't sign in, your CV, job
                descriptions, and analyses are kept only in your browser (localStorage) —
                they are never stored on our servers, and clearing your browser data removes them.
              </p>
              <p>
                <strong>AI processing.</strong> The text you submit is sent to our AI provider
                (Groq) to generate the analysis. ApplyLens does not persist that text; the
                provider handles it under its own policies.
              </p>
              <p>
                <strong>Optional accounts.</strong> If you create an account, we store your
                email and the applications you choose to save (title, company, status, and the
                saved analysis) so they sync across your devices. You can delete any saved
                application at any time, and request account deletion.
              </p>
              <p>
                <strong>No selling, no ads, no tracking.</strong> We don't sell or share your
                data, and there are no third-party trackers or advertising.
              </p>
              <p className="privacy__note">
                ApplyLens is a personal/portfolio project and is provided “as is,” without warranty.
              </p>
            </div>
          </div>
        </div>
      )}
    </footer>
  )
}
