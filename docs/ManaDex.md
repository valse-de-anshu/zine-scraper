# 📚 MangaDex Setup

A quick 2-step guide to setting up your personal API keys and downloading manga with Zine Scraper.

---

### Step 1: Create Your Personal API Key
1. Log in
2. open [MangaDex API Settings](https://mangadex.org/settings#api-clients).
3. Scroll down to **Personal Clients**, click **Create Client**, name it whatever u want, and hit **Save**:

<p align="center">
  <img src="guide assets/MangaDex/api/api creation.png" alt="API Creation" width="700">
</p>

4. Copy your **Client ID** and **Client Secret** :

<p align="center">
  <img src="guide assets/MangaDex/api/copy : api key & client id  .png" alt="Copy Credentials" width="700">
</p>

---

### Step 2: Paste Into `secrets.json`
Open `secrets.json` in your Zine folder (auto-generated on first launch) and paste your keys:

```json
{
    "mangadex": {
        "client_id": "personal-client-your-client-id-here",
        "client_secret": "your-client-secret-here"
    }
}
```

> [!NOTE]
> `secrets.json` is strictly ignored by Git (`.gitignore`) and will never be tracked, committed, or leaked.

---
