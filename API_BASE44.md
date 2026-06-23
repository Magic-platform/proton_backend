# Documentation API Mail Proton

Base URL :

```txt
https://proton.api.abrakdabra.io
```

Toutes les routes nécessitent le header d'authentification :

```txt
Authorization: Bearer TON_API_TOKEN
```

Réponses d'erreur communes :

```txt
401 unauthorized  -> token absent ou invalide
400 bad request   -> paramètre invalide ou header obligatoire manquant
404 not found     -> ressource demandée introuvable
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
  "text": "Contenu texte du mail",
  "html": "<p>Contenu <strong>HTML</strong> du mail</p>"
}
```

Champs :

```txt
to      required, liste d'emails, min 1
cc      optional, liste d'emails
bcc     optional, liste d'emails cachés
subject required, string, max 255
text    required, string
html    optional, string HTML
```

Si `html` est fourni, l'email est envoyé en `multipart/alternative` avec une version `text/plain` et une version `text/html`. Les clients mail affichent généralement la version HTML automatiquement.

Réponse succès :

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
    text: "Message envoyé depuis Base44.",
    html: "<p>Message envoyé depuis <strong>Base44</strong>.</p>"
  })
});
```

## Récupérer La Boîte Inbox

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

Limites appliquées côté backend :

```txt
include_body=true   -> max 200 emails par appel
include_body=false  -> max 1000 emails par appel
```

Premier appel recommandé :

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

Réponse :

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
has_more=false         -> plus rien à charger
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

- `bcc` fonctionne pour l'envoi, mais n'apparaît jamais dans les emails reçus.
- `/inbox` lit les mails avec `BODY.PEEK`, donc il ne marque pas les emails comme lus.
- `uid` est l'identifiant à stocker côté Base44 pour reconnaître un email.
- `body_text` contient la version texte quand l'email fournit une partie `text/plain`.
- `body_html` contient le HTML brut quand l'email fournit une partie `text/html`.
- Si `include_body=false`, `body_text`, `body_html` et `snippet` sont retournés à `null`.
- Pour un affichage rapide : utiliser `include_body=false`.
- Pour exploiter le contenu complet : utiliser `include_body=true`.

## Variables À Stocker Côté Base44

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

## Programmer Un Email

```http
POST /scheduled-mails
Content-Type: application/json
Authorization: Bearer TON_API_TOKEN
Idempotency-Key: base44-email-unique-id
```

Body :

```json
{
  "to": ["client@example.com"],
  "cc": [],
  "bcc": [],
  "subject": "Sujet programmé",
  "text": "Version texte du message",
  "html": "<p>Version <strong>HTML</strong> du message</p>",
  "scheduled_at": "2026-06-23T15:30:00Z",
  "base44_email_id": "optional-base44-id"
}
```

Champs :

```txt
to               required, liste d'emails, min 1
cc               optional, liste d'emails
bcc              optional, liste d'emails cachés
subject          required, string, max 255
text             required, string
html             optional, string HTML
scheduled_at     required, date ISO 8601 avec timezone, stockée en UTC
base44_email_id  optional, id côté Base44
```

`Idempotency-Key` est obligatoire. Si Base44 envoie deux fois la même clé, l'API retourne le même email programmé au lieu d'en créer un deuxième.

La réponse peut donc contenir un statut autre que `pending` si la clé a déjà été utilisée pour un email déjà envoyé, annulé ou échoué.

Réponse :

```json
{
  "id": "uuid",
  "status": "pending",
  "scheduled_at": "2026-06-23T15:30:00Z"
}
```

## Suivre Les Emails Programmés

```http
GET /scheduled-mails
Authorization: Bearer TON_API_TOKEN
```

Query params :

```txt
status             optional: pending, processing, sent, failed, cancelled
limit              optional, default 50, max 200
before_created_at  optional, pagination par created_at
```

Réponse :

```json
{
  "items": [
    {
      "id": "uuid",
      "idempotency_key": "base44-email-unique-id",
      "base44_email_id": "optional-base44-id",
      "to": ["client@example.com"],
      "cc": [],
      "bcc": [],
      "subject": "Sujet programmé",
      "text": "Version texte du message",
      "html": "<p>Version HTML</p>",
      "scheduled_at": "2026-06-23T15:30:00Z",
      "status": "pending",
      "attempts": 0,
      "max_attempts": 3,
      "locked_at": null,
      "last_attempt_at": null,
      "sent_at": null,
      "error": null,
      "created_at": "2026-06-23T10:00:00Z",
      "updated_at": "2026-06-23T10:00:00Z"
    }
  ],
  "count": 1
}
```

Detail :

```http
GET /scheduled-mails/{id}
Authorization: Bearer TON_API_TOKEN
```

Annulation :

```http
POST /scheduled-mails/{id}/cancel
Authorization: Bearer TON_API_TOKEN
```

Réponse :

```json
{
  "id": "uuid",
  "status": "cancelled"
}
```

Notes :

- Un email peut être annulé seulement si son statut est `pending` ou `failed`.
- Si l'email est déjà `sent`, `processing` ou `cancelled`, l'endpoint retourne son statut actuel sans le modifier.
- Le VPS envoie les emails dus via un worker systemd toutes les minutes.
- En cas d'erreur SMTP, le worker retente jusqu'à 3 fois.
- Les statuts possibles sont `pending`, `processing`, `sent`, `failed`, `cancelled`.

Erreurs spécifiques :

```txt
POST /scheduled-mails
400 -> header Idempotency-Key manquant
422 -> payload invalide ou scheduled_at sans timezone

GET /scheduled-mails
400 -> status invalide

GET /scheduled-mails/{id}
404 -> email programmé introuvable

POST /scheduled-mails/{id}/cancel
404 -> email programmé introuvable
```
