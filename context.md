# Contexte Proton Bridge + FastAPI sur VPS

## Objectif

Construire un backend Python FastAPI sur un VPS qui sert de passerelle mail pour un compte Proton Mail.

Le backend doit pouvoir :

- envoyer des emails depuis Proton via SMTP ;
- lire les emails via IMAP ;
- exposer une API HTTPS utilisable par un frontend, un CRM ou une automatisation ;
- garder les ports Proton Bridge non exposés à Internet ;
- tourner en continu après redémarrage du VPS.

## Principe Important

Proton Mail ne fournit pas une API mail classique comparable à Gmail API pour accéder directement aux emails. Pour IMAP/SMTP, la voie standard est **Proton Mail Bridge**.

Proton Bridge agit comme un proxy local :

```text
FastAPI backend
   |
   | IMAP/SMTP local
   v
Proton Bridge
   |
   | connexion Proton
   v
Proton Mail
```

Le backend ne parle donc pas directement à Proton. Il parle à Bridge comme à un serveur mail local.

Ports généralement utilisés par Proton Bridge :

- IMAP : `127.0.0.1:1143`
- SMTP : `127.0.0.1:1025`

Ces ports doivent rester accessibles uniquement localement.

## Architecture Recommandée

Sur le VPS :

```text
Internet
   |
HTTPS
   |
Caddy ou Nginx
   |
127.0.0.1:8787
   |
FastAPI backend
   |
   | SMTP 127.0.0.1:1025
   | IMAP 127.0.0.1:1143
   v
Proton Bridge
```

Services à lancer :

```text
proton-bridge.service    # Proton Bridge sur le VPS
mail-api.service         # FastAPI
caddy.service            # HTTPS reverse proxy
```

Le reverse proxy expose seulement FastAPI. Les ports IMAP/SMTP Bridge ne sont jamais ouverts publiquement.

## Variables D'environnement

Exemple de fichier `/opt/mail-api/.env` :

```env
API_TOKEN=long_token_random

BRIDGE_HOST=127.0.0.1
BRIDGE_IMAP_PORT=1143
BRIDGE_SMTP_PORT=1025
BRIDGE_USER=cabinet@protonmail.com
BRIDGE_PASS=mot_de_passe_bridge_pas_le_mot_de_passe_proton
TLS_VERIFY=false
```

Point important : `BRIDGE_PASS` n'est pas le mot de passe Proton principal. C'est le mot de passe généré par Proton Bridge pour les clients IMAP/SMTP.

## Exemple FastAPI Minimal

```python
import os
import ssl
import smtplib
import imaplib
import email
from email.message import EmailMessage

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel

app = FastAPI()

API_TOKEN = os.environ["API_TOKEN"]
HOST = os.getenv("BRIDGE_HOST", "127.0.0.1")
SMTP_PORT = int(os.getenv("BRIDGE_SMTP_PORT", "1025"))
IMAP_PORT = int(os.getenv("BRIDGE_IMAP_PORT", "1143"))
USER = os.environ["BRIDGE_USER"]
PASS = os.environ["BRIDGE_PASS"]
TLS_VERIFY = os.getenv("TLS_VERIFY", "false") == "true"


def check_auth(authorization: str | None):
    if authorization != f"Bearer {API_TOKEN}":
        raise HTTPException(status_code=401, detail="unauthorized")


def tls_context():
    ctx = ssl.create_default_context()
    if not TLS_VERIFY:
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    return ctx


class SendMail(BaseModel):
    to: str
    subject: str
    text: str
    from_addr: str | None = None


@app.get("/health")
def health(authorization: str | None = Header(default=None)):
    check_auth(authorization)
    return {"ok": True}


@app.post("/send")
def send_mail(payload: SendMail, authorization: str | None = Header(default=None)):
    check_auth(authorization)

    msg = EmailMessage()
    msg["From"] = payload.from_addr or USER
    msg["To"] = payload.to
    msg["Subject"] = payload.subject
    msg.set_content(payload.text)

    with smtplib.SMTP(HOST, SMTP_PORT, timeout=20) as smtp:
        smtp.starttls(context=tls_context())
        smtp.login(USER, PASS)
        smtp.send_message(msg)

    return {"ok": True}


@app.get("/inbox")
def inbox(limit: int = 20, authorization: str | None = Header(default=None)):
    check_auth(authorization)

    with imaplib.IMAP4(HOST, IMAP_PORT, timeout=20) as imap:
        imap.starttls(ssl_context=tls_context())
        imap.login(USER, PASS)
        imap.select("INBOX")

        typ, data = imap.uid("search", None, "ALL")
        uids = data[0].split()[-limit:]
        items = []

        for uid in reversed(uids):
            typ, msg_data = imap.uid("fetch", uid, "(RFC822.HEADER)")
            raw = msg_data[0][1]
            parsed = email.message_from_bytes(raw)
            items.append({
                "uid": uid.decode(),
                "from": parsed.get("From"),
                "subject": parsed.get("Subject"),
                "date": parsed.get("Date"),
            })

        return {"messages": items}
```

Pour une version plus solide, utiliser :

- `aiosmtplib` pour SMTP async ;
- `imapclient`, `aioimaplib` ou une librairie IMAP plus ergonomique que `imaplib` ;
- une base PostgreSQL pour indexer les messages utiles ;
- Redis/Celery/RQ/Arq pour les envois programmés ou traitements en arrière-plan.

## Pourquoi Ne Pas Lancer Simplement `fastapi run app.py`

La commande peut fonctionner :

```bash
fastapi run app.py
```

Mais lancée à la main, elle dépend de la session SSH. Si la session se ferme, si le process plante, ou si le VPS redémarre, le service s'arrête.

En production, le problème n'est pas la commande FastAPI. Le problème est la supervision.

Il faut un superviseur :

- redémarrage automatique ;
- lancement au boot ;
- logs centralisés ;
- variables d'environnement propres ;
- statut clair ;
- arrêt/redémarrage propre.

Sur Ubuntu, le superviseur standard est `systemd`.

## Service systemd Pour FastAPI

Créer :

```ini
# /etc/systemd/system/mail-api.service
[Unit]
Description=Mail API FastAPI
After=network.target

[Service]
User=ubuntu
WorkingDirectory=/opt/mail-api
EnvironmentFile=/opt/mail-api/.env
ExecStart=/opt/mail-api/.venv/bin/uvicorn app:app --host 127.0.0.1 --port 8787
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
```

Commandes :

```bash
sudo systemctl daemon-reload
sudo systemctl enable mail-api
sudo systemctl start mail-api
sudo systemctl status mail-api
```

Logs :

```bash
sudo journalctl -u mail-api -f
sudo journalctl -u mail-api -n 100
```

Redémarrage :

```bash
sudo systemctl restart mail-api
```

Si tu préfères utiliser la commande FastAPI officielle :

```ini
ExecStart=/opt/mail-api/.venv/bin/fastapi run app.py --host 127.0.0.1 --port 8787
```

Mais `uvicorn app:app` reste le format classique et explicite.

## Service systemd Pour Proton Bridge

Proton Bridge doit aussi tourner en continu.

Le service dépendra du chemin réel de l'exécutable Bridge et du mode CLI disponible sur le VPS. Le principe :

```ini
# /etc/systemd/system/proton-bridge.service
[Unit]
Description=Proton Mail Bridge
After=network.target

[Service]
User=ubuntu
WorkingDirectory=/home/ubuntu
ExecStart=/usr/bin/protonmail-bridge --cli
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

Commandes :

```bash
sudo systemctl daemon-reload
sudo systemctl enable proton-bridge
sudo systemctl start proton-bridge
sudo systemctl status proton-bridge
sudo journalctl -u proton-bridge -f
```

Le chemin `ExecStart` doit être adapté à l'installation réelle.

## Docker Ou Pas Docker

Deux options existent :

```text
Option A : Proton Bridge installé directement sur Ubuntu
Option B : Proton Bridge dans Docker
```

### Option A - Bridge Sur L'hôte

Recommandation de départ.

Avantages :

- plus simple à déboguer ;
- conforme au fonctionnement naturel de Bridge ;
- pas de problème réseau entre conteneur et hôte ;
- accès direct à `127.0.0.1:1025` et `127.0.0.1:1143` ;
- gestion simple avec `systemd`.

Architecture :

```text
FastAPI hôte -> 127.0.0.1:1025/1143 -> Bridge hôte
```

### Option B - Bridge Dans Docker

Possible, mais à traiter comme une décision d'exploitation, pas comme un prérequis.

Avantages :

- configuration reproductible ;
- volumes séparés ;
- redémarrage via `restart: unless-stopped` ;
- déploiement plus portable.

Réserves importantes :

- Proton Bridge en Docker repose souvent sur des images communautaires, pas forcément officielles ;
- Bridge n'est pas une app stateless : il gère session, cache, secrets et stockage local ;
- le réseau Docker ajoute de la complexité ;
- si FastAPI est aussi dans Docker, `127.0.0.1` du conteneur n'est pas celui du VPS ;
- il faut vérifier précisément quels ports l'image expose ;
- Docker ne change pas le fait que les mails sont déchiffrés sur le VPS.

Si Bridge est dans Docker et FastAPI sur l'hôte, tu peux mapper les ports uniquement sur localhost :

```yaml
ports:
  - "127.0.0.1:1025:1025"
  - "127.0.0.1:1143:1143"
```

Mais les ports internes dépendent de l'image choisie.

Si FastAPI est aussi dans Docker, options :

- utiliser un réseau Docker commun et parler au service Bridge par nom DNS ;
- utiliser `network_mode: host` ;
- mapper les ports Bridge vers l'hôte.

Tout cela est plus complexe que l'installation directe.

## Recommandation Pratique

Pour commencer :

```text
Proton Bridge : systemd sur l'hôte
FastAPI       : systemd sur l'hôte
Caddy/Nginx   : systemd sur l'hôte
Postgres      : optionnel, Docker possible
Redis         : optionnel, Docker possible
```

Commencer simple permet de valider rapidement :

- authentification Bridge ;
- envoi SMTP ;
- lecture IMAP ;
- stabilité du service ;
- exposition HTTPS de l'API.

Docker peut venir plus tard pour FastAPI ou les dépendances secondaires. Pour Proton Bridge, il faut une vraie raison opérationnelle avant de dockeriser.

## Sécurité

Points à respecter :

- ne jamais exposer `1025` ou `1143` publiquement ;
- bind FastAPI sur `127.0.0.1` derrière Caddy/Nginx ;
- exposer seulement HTTPS ;
- protéger toutes les routes par bearer token ou auth plus forte ;
- stocker les secrets dans un fichier `.env` non versionné ;
- restreindre les permissions du `.env` :

```bash
sudo chmod 600 /opt/mail-api/.env
```

- utiliser un utilisateur Linux dédié si possible ;
- surveiller les logs ;
- mettre à jour le VPS régulièrement.

Exemple Caddy :

```caddy
mail-api.example.com {
    reverse_proxy 127.0.0.1:8787
    encode gzip
}
```

## Risque De Sécurité Inhérent Au VPS

Avec Proton Bridge sur un VPS, les emails sont déchiffrés localement sur ce VPS.

Cela peut être acceptable pour une passerelle mail contrôlée, mais il faut comprendre la conséquence :

```text
Le VPS devient une machine de confiance.
```

Il faut donc le durcir :

- SSH par clé uniquement ;
- pas de mot de passe SSH ;
- firewall actif ;
- ports strictement nécessaires ;
- mises à jour automatiques de sécurité ;
- logs surveillés ;
- backups chiffrés si stockage local.

## Ordre D'implémentation Conseillé

1. Installer Proton Bridge sur le VPS.
2. Se connecter au compte Proton dans Bridge.
3. Vérifier les ports locaux IMAP/SMTP.
4. Tester SMTP en local avec un petit script Python.
5. Tester IMAP en local avec un petit script Python.
6. Créer l'app FastAPI minimale.
7. Lancer FastAPI avec `systemd`.
8. Mettre Caddy/Nginx devant.
9. Ajouter l'auth API.
10. Ajouter endpoints métier : `/send`, `/inbox`, `/message/{uid}`, `/reply`, `/flag`.
11. Ajouter queue ou jobs de polling si besoin.

## Conclusion

La bonne base est :

```text
FastAPI supervise par systemd
        |
        | localhost IMAP/SMTP
        v
Proton Bridge supervise par systemd
        |
        v
Proton Mail
```

Docker n'est pas interdit, mais il n'est pas nécessaire pour le premier déploiement. Le plus important est de ne jamais exposer Bridge directement et de faire superviser FastAPI + Bridge par `systemd`.
