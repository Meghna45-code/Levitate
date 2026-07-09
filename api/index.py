import os
import sys

# Ensure the root directory and Vercel task environments are in Python's search path
sys.path.append("/var/task")
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

import traceback

try:
    from backend.app.main import app as _app
    app = _app
except Exception as e:
    tb = traceback.format_exc()
    print(f"CRITICAL STARTUP ERROR:\n{tb}", file=sys.stderr)
    
    async def fallback_app(scope, receive, send):
        if scope['type'] != 'http':
            return
        
        html = f"""<!DOCTYPE html>
<html>
<head>
    <title>Startup Error (500)</title>
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; padding: 40px; background-color: #fcfcfc; color: #333; }}
        .card {{ max-width: 800px; margin: 0 auto; background: white; border: 1px solid #e1e4e8; border-radius: 6px; padding: 32px; box-shadow: 0 4px 12px rgba(0,0,0,0.05); }}
        h1 {{ color: #d73a49; margin-top: 0; font-size: 24px; border-bottom: 1px solid #e1e4e8; padding-bottom: 12px; }}
        pre {{ background: #f6f8fa; padding: 16px; border-radius: 3px; overflow-x: auto; font-size: 14px; line-height: 1.5; color: #24292e; border: 1px solid #e1e4e8; }}
        .info {{ margin-top: 20px; font-size: 14px; color: #586069; }}
    </style>
</head>
<body>
    <div class="card">
        <h1>Critical Startup Error (500)</h1>
        <p>The Python application failed to initialize during import on Vercel:</p>
        <pre>{tb}</pre>
        <div class="info">
            <strong>sys.path:</strong> {sys.path}<br>
            <strong>CWD:</strong> {os.getcwd()}
        </div>
    </div>
</body>
</html>"""
        response_body = html.encode('utf-8')
        await send({
            'type': 'http.response.start',
            'status': 500,
            'headers': [
                (b'content-type', b'text/html; charset=utf-8'),
                (b'content-length', str(len(response_body)).encode('utf-8')),
            ],
        })
        await send({
            'type': 'http.response.body',
            'body': response_body,
        })
        
    app = fallback_app




