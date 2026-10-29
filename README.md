# Dobara — pre-loved saree shop

A Python (Flask + SQLite) version of the Dobara artifact, with a password-protected admin back office.

## Run it

```powershell
cd C:\Users\ramg\Desktop\Python\Dobara
pip install -r requirements.txt
python app.py
```

- Shop: http://127.0.0.1:5000
- Admin: http://127.0.0.1:5000/admin. On the first visit you create the owner account.

On first start the database (`instance/dobara.db`) is filled from `seed.json`: your shop settings and the 5 sarees from the artifact, including the Kanjeevaram photo.

### Production / sharing on your network

```powershell
python serve.py            # waitress on http://0.0.0.0:8000
```

Environment variables (all optional):

| Variable | Purpose |
|---|---|
| `DOBARA_SECRET_KEY` | Session signing key. Without it, one is generated into `instance/secret_key`. |
| `DOBARA_DB` | Path to the SQLite file (default `instance/dobara.db`). |
| `DOBARA_SECURE_COOKIES=1` | Set this when the site is served over HTTPS. |
| `HOST`, `PORT` | Bind address and port. |

## What the shop does
The shop works like the artifact did:
- Search, a fabric filter, sorting, category chips, "New since your last visit", and saved sarees (hearts, kept on each visitor's device)
- A detail view for each saree
- "Order on WhatsApp", "Send photos" and "Tell me" buttons. Every tap is counted for the dashboard.

## Admin
- **Dashboard:** counts by status, stock value, sales this month and all time, WhatsApp taps (last 30 days), the most-asked-about sarees, items on hold, recent sales, CSV and JSON backups.
- **Sarees:** add, edit or delete sarees and upload photos, which are auto-rotated and resized. Each saree has one of four statuses:
  - **Available:** shown on the shop and can be ordered.
  - **On hold:** shown, but can't be ordered.
  - **Sold:** shown greyed out.
  - **Hidden:** a draft that isn't shown.
  
  You can also search and filter the list.
- **Lists:** manage categories (the shop's filter chips), fabrics and conditions. Renaming an entry updates every saree that uses it.
- **Shop settings:** name, tagline, WhatsApp number, currency, the "How buying works" steps, the "Sell yours" text and the footer.
- **Admins:** add or remove admin accounts. **My account** changes your password.

Security: passwords are hashed, every form has CSRF protection, and there's a short lockout after 5 failed sign-ins.

## Back up
Copy `instance/dobara.db` and `static/uploads/`. That's everything.
