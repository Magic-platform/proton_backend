# Documentation API Mail Proton

Base URL :

```txt
https://proton.api.abrakdabra.io
```

Toutes les routes necessitent le header d'authentification :

```txt
Authorization: Bearer TON_API_TOKEN
```

Reponses d'erreur communes :

```txt
401 unauthorized  -> token absent ou invalide
422 validation    -> payload ou email invalide
500 server error  -> erreur SMTP/IMAP/Proton Bridge
```

## Envoyer Un Email

```http
POST /send
Content-Type: application/json
Authorization: Bearer TON_API_TOKEN
```

Body :

```json
{
  "to": ["client@example.com"],
  "cc": ["copie@example.com"],
  "bcc": ["archive@example.com"],
  "subject": "Sujet du mail",
  "text": "Contenu texte du mail"
}
```

Champs :

```txt
to      required, liste d'emails, min 1
cc      optional, liste d'emails
bcc     optional, liste d'emails caches
subject required, string, max 255
text    required, string
```

Reponse succes :

```json
{
  "ok": true
}
```

Exemple JavaScript :

```js
await fetch("https://proton.api.abrakdabra.io/send", {
  method: "POST",
  headers: {
    "Content-Type": "application/json",
    "Authorization": `Bearer ${MAIL_API_TOKEN}`
  },
  body: JSON.stringify({
    to: ["client@example.com"],
    cc: [],
    bcc: [],
    subject: "Bonjour",
    text: "Message envoye depuis Base44."
  })
});
```

## Recuperer La Boite Inbox

```http
GET /inbox
Authorization: Bearer TON_API_TOKEN
```

Query params :

```txt
limit         optional, default 100
mailbox       optional, default INBOX
unread_only   optional, default false
before_uid    optional, pagination
include_body  optional, default true
```

Limites appliquees cote backend :

```txt
include_body=true   -> max 200 emails par appel
include_body=false  -> max 1000 emails par appel
```

Premier appel recommande :

```txt
GET /inbox?limit=100&include_body=true
```

Page suivante :

```txt
GET /inbox?limit=100&include_body=true&before_uid=12345
```

Afficher beaucoup d'emails rapidement, sans contenu complet :

```txt
GET /inbox?limit=500&include_body=false
```

Reponse :

```json
{
  "messages": [
    {
      "uid": "12345",
      "message_id": "<message-id@example.com>",
      "from": {
        "name": "Client Test",
        "email": "client@example.com"
      },
      "to": [
        {
          "name": "Cabinet",
          "email": "cabinet@proton.me"
        }
      ],
      "cc": [],
      "subject": "Demande de rendez-vous",
      "date": "2026-06-07T10:30:00+02:00",
      "seen": false,
      "answered": false,
      "flagged": false,
      "snippet": "Bonjour, je souhaite prendre rendez-vous...",
      "body_text": "Bonjour, je souhaite prendre rendez-vous...",
      "body_html": "<div>Bonjour, je souhaite prendre rendez-vous...</div>"
    }
  ],
  "count": 1,
  "has_more": true,
  "next_before_uid": "12345"
}
```

Pagination :

```txt
has_more=true          -> il reste des emails plus anciens
next_before_uid=12345  -> utiliser cette valeur dans le prochain appel
has_more=false         -> plus rien a charger
```

Exemple JavaScript :

```js
const res = await fetch(
  "https://proton.api.abrakdabra.io/inbox?limit=100&include_body=true",
  {
    headers: {
      "Authorization": `Bearer ${MAIL_API_TOKEN}`
    }
  }
);

if (!res.ok) {
  throw new Error(`Mail API error: ${res.status}`);
}

const inbox = await res.json();
```

Page suivante :

```js
const res = await fetch(
  `https://proton.api.abrakdabra.io/inbox?limit=100&include_body=true&before_uid=${inbox.next_before_uid}`,
  {
    headers: {
      "Authorization": `Bearer ${MAIL_API_TOKEN}`
    }
  }
);

if (!res.ok) {
  throw new Error(`Mail API error: ${res.status}`);
}

const nextPage = await res.json();
```

## Notes

- `bcc` fonctionne pour l'envoi, mais n'apparait jamais dans les emails recus.
- `/inbox` lit les mails avec `BODY.PEEK`, donc il ne marque pas les emails comme lus.
- `uid` est l'identifiant a stocker cote Base44 pour reconnaitre un email.
- `body_text` contient la version texte quand l'email fournit une partie `text/plain`.
- `body_html` contient le HTML brut quand l'email fournit une partie `text/html`.
- Si `include_body=false`, `body_text`, `body_html` et `snippet` sont retournes a `null`.
- Pour un affichage rapide : utiliser `include_body=false`.
- Pour exploiter le contenu complet : utiliser `include_body=true`.

## Variables A Stocker Cote Base44

```txt
MAIL_API_BASE_URL=https://proton.api.abrakdabra.io
MAIL_API_TOKEN=TON_API_TOKEN
```

## Exemple Fonction Base44

```js
const baseUrl = Deno.env.get("MAIL_API_BASE_URL");
const token = Deno.env.get("MAIL_API_TOKEN");

const response = await fetch(`${baseUrl}/inbox?limit=100&include_body=true`, {
  headers: {
    Authorization: `Bearer ${token}`
  }
});

if (!response.ok) {
  throw new Error(`Mail API error: ${response.status}`);
}

const inbox = await response.json();
return Response.json(inbox);
```
