// POST /api/subscribe — add an email to the The Daily Butler Resend audience.
// Env vars (set on Vercel): RESEND_API_KEY, RESEND_AUDIENCE_ID
export default async function handler(req, res) {
  if (req.method !== 'POST') {
    return res.status(405).json({ ok: false, message: 'Method not allowed' });
  }
  let body;
  try { body = req.body || {}; } catch { body = {}; }
  const email = String(body.email || '').trim().toLowerCase();

  if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) {
    return res.status(400).json({ ok: false, message: 'Invalid email address.' });
  }

  const apiKey = process.env.RESEND_API_KEY;
  const audienceId = process.env.RESEND_AUDIENCE_ID;
  if (!apiKey || !audienceId) {
    // Fail closed in prod, but let local preview through with a clear message.
    return res.status(500).json({ ok: false, message: 'Newsletter is not configured yet.' });
  }

  try {
    const r = await fetch('https://api.resend.com/subscribers', {
      method: 'POST',
      headers: { Authorization: `Bearer ${apiKey}`, 'Content-Type': 'application/json' },
      body: JSON.stringify({ email, audience_id: audienceId }),
    });
    const data = await r.json().catch(() => ({}));
    if (!r.ok) {
      // Resend returns 422 when the email is already subscribed.
      if (r.status === 422) {
        return res.status(200).json({ ok: true, message: 'Already subscribed — you are on the list.' });
      }
      console.error('resend error', r.status, data);
      return res.status(502).json({ ok: false, message: 'Could not subscribe. Try again in a moment.' });
    }
    return res.status(200).json({ ok: true, message: 'Subscribed.' });
  } catch (err) {
    console.error('subscribe fetch failed', err);
    return res.status(500).json({ ok: false, message: 'Something went wrong. Try again.' });
  }
}
