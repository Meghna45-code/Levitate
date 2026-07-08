# Implementation Plan: SMTP Email Configuration

This plan details how to configure SMTP support in the Levitate backend to send real verification and password reset PINs (OTPs) to users' email addresses.

## User Review Required

> [!IMPORTANT]
> - By default, the application will fall back to "demo mode" if `SEND_REAL_EMAILS` is set to `False` or if SMTP settings are not provided.
> - When `SEND_REAL_EMAILS=True`, the 6-digit verification and reset PINs will no longer be visible on-screen (the green demo badge will stay hidden), and users must retrieve the PIN from their actual inbox.
> - For Gmail accounts, using a personal account password directly might fail; users should configure a **Gmail App Password** under Google Account security.

---

## Proposed Changes

### 1. Environment Configuration
#### [MODIFY] [backend/.env](file:///c:/Users/HP/OneDrive/Desktop/Levitate/backend/.env)
Add environment variables for SMTP configuration:
```ini
# Real SMTP Email Configuration
SEND_REAL_EMAILS=False
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USERNAME=your-email@gmail.com
SMTP_PASSWORD=your-app-password
SMTP_SENDER=your-email@gmail.com
```

#### [MODIFY] [config.py](file:///c:/Users/HP/OneDrive/Desktop/Levitate/backend/app/config.py)
Map these environment variables to settings inside the `Settings` class:
```python
SEND_REAL_EMAILS: bool = os.getenv("SEND_REAL_EMAILS", "False").lower() in ("true", "1", "yes")
SMTP_HOST: str = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT: int = int(os.getenv("SMTP_PORT", "587"))
SMTP_USERNAME: str = os.getenv("SMTP_USERNAME", "")
SMTP_PASSWORD: str = os.getenv("SMTP_PASSWORD", "")
SMTP_SENDER: str = os.getenv("SMTP_SENDER", "")
```

---

### 2. Email Service Component
#### [NEW] [email.py](file:///c:/Users/HP/OneDrive/Desktop/Levitate/backend/app/services/email.py)
Implement a robust helper using standard library `smtplib` and `email.mime` modules:
- Functions:
  - `send_otp_email_task(recipient: str, otp: str, is_reset: bool = False)`: Establishes a TLS SMTP connection, logs in, constructs an HTML/Text email, and transmits it.
  - Safe error handling: If email transmission fails, catch exceptions and log them to standard error, ensuring the backend server does not crash.

---

### 3. API Route Enhancements
#### [MODIFY] [main.py](file:///c:/Users/HP/OneDrive/Desktop/Levitate/backend/app/main.py)
- Import `BackgroundTasks` from `fastapi` and `send_otp_email_task` from `backend.app.services.email`.
- Update `@app.post("/api/auth/signup")`:
  - Accept `background_tasks: BackgroundTasks`.
  - If `settings.SEND_REAL_EMAILS` is enabled, queue the `send_otp_email_task` with `is_reset=False`.
  - Conditionally omit returning `otp` in the JSON response if `settings.SEND_REAL_EMAILS` is active.
- Update `@app.post("/api/auth/forgot-password")`:
  - Accept `background_tasks: BackgroundTasks`.
  - If `settings.SEND_REAL_EMAILS` is enabled, queue the `send_otp_email_task` with `is_reset=True`.
  - Conditionally omit returning `otp` in the JSON response if `settings.SEND_REAL_EMAILS` is active.

---

## Verification Plan

### Automated Tests
We will add automated tests in `test_pipeline.py` or a dedicated test script to verify that:
1. When `SEND_REAL_EMAILS` is active, the endpoints do not expose `otp` in their response payloads.
2. The background task executes and calls the email-sending module correctly.
3. The email service successfully initiates SMTP commands (tested with mock SMTP servers).

### Manual Verification
1. Set up a real SMTP credential in `backend/.env`.
2. Turn on `SEND_REAL_EMAILS=True`.
3. Perform a signup in the browser and confirm that a real verification email is delivered to your inbox, and that no OTP badge is shown on the signup page.
