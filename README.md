# Telegram Stars Number Shop

Պատրաստի Telegram bot՝ Telegram Stars-ով օրինականորեն վերահսկվող/տրամադրված հեռախոսահամարների վաճառքի համար։

## Ինչ է օգտագործվում

- Python 3.11+
- python-telegram-bot 22.8
- SQLite
- python-dotenv
- Telegram Stars (`XTR`)
- Railway-compatible polling deployment

Telegram Stars payment flow-ը օգտագործում է Telegram-ի պաշտոնական `sendInvoice` → `pre_checkout_query` → `successful_payment` ընթացքը։ Stars-ի համար invoice-ի currency-ն `XTR` է, իսկ provider token-ը դատարկ է։

## Project structure

Այս ZIP-ի մեջ կա միայն մեկ project պանակ, և դրա ներսում ֆայլերն են.

```text
telegram_stars_number_shop/
├── bot.py
├── database.py
├── config.py
├── payment.py
├── requirements.txt
├── Procfile
├── .env.example
└── README.md
```

SQLite database-ը ստեղծվում է առաջին գործարկման ժամանակ որպես `bot.db`։ Լրացուցիչ project/data ենթապանակ պետք չէ։

---

# 1. BotFather

Telegram-ում բացեք `@BotFather` և ստեղծեք bot.

1. `/newbot`
2. տվեք bot-ի անունը
3. տվեք username-ը
4. ստացեք `BOT_TOKEN`

Token-ը ոչ մեկին մի ուղարկեք և մի տեղադրեք Python source code-ի մեջ։

---

# 2. OWNER_ID

OWNER_ID-ը ձեր Telegram numeric user ID-ն է։

Օրինակ՝

```text
OWNER_ID=123456789
```

Այն պետք է լինի հենց ձեր Telegram account-ի numeric ID-ն, ոչ թե username-ը։

---

# 3. Environment variables

`.env.example`-ը կարող եք պատճենել `.env` և լրացնել.

```env
BOT_TOKEN=123456:ABC...
OWNER_ID=123456789
```

Railway-ում `.env` ֆայլը պարտադիր չէ. ավելի ճիշտ է Variables բաժնում ստեղծել նույն անուններով variables։

Պետք է լինեն.

```text
BOT_TOKEN
OWNER_ID
```

Optional.

```text
DB_PATH
```

---

# 4. Տեղական գործարկում

Python 3.11+ ունենալու դեպքում.

```bash
python -m venv .venv
```

Linux/macOS.

```bash
source .venv/bin/activate
```

Windows.

```powershell
.venv\Scripts\activate
```

Տեղադրեք dependencies.

```bash
pip install -r requirements.txt
```

Ստեղծեք `.env` և լրացրեք `BOT_TOKEN` ու `OWNER_ID`։

Գործարկեք.

```bash
python bot.py
```

Bot-ը աշխատում է polling-ով, դրա համար առանձին web server կամ public port պետք չէ։

---

# 5. Railway deployment

1. Ստեղծեք Railway account։
2. Ստեղծեք New Project։
3. Deploy from GitHub կամ upload/import արեք այս project-ը։
4. Railway-ում Variables բաժնում ավելացրեք.

```text
BOT_TOKEN=ձեր BotFather token-ը
OWNER_ID=ձեր numeric Telegram ID-ն
```

5. Deploy արեք։
6. Logs-ում պետք է տեսնեք.

```text
Bot starting...
```

Եթե deployment-ը օգտագործում է Procfile-ը, worker command-ը կլինի.

```text
python bot.py
```

Այս project-ը հատուկ HTTP port չի պահանջում։

---

# 6. Տվյալների պահպանում՝ Railway restart-ի և նոր account-ի դեպքում

Այս bot-ը ունի երկու մակարդակի պաշտպանություն։

### A. Նույն Railway project-ի restart/redeploy

SQLite-ը պահվում է `DB_PATH`-ում։ Default-ը՝

```text
bot.db
```

Եթե Railway-ում օգտագործում եք Persistent Volume, Variables-ում դրեք, օրինակ՝

```env
DB_PATH=/data/bot.db
```

Այդ դեպքում նույն Railway project-ի restart/redeploy-ի ժամանակ database-ը կմնա Volume-ում։

### B. Նոր Railway account/project տեղափոխվելիս

Railway Volume-ը նոր account/project ինքն իրեն չի տեղափոխվում։ Այդ պատճառով bot-ը **ավտոմատ backup է ուղարկում ձեր OWNER_ID-ի Telegram chat-ին** ամենակարևոր տվյալների փոփոխությունից հետո՝

- նոր համար ավելացնելուց հետո,
- համար վաճառվելուց հետո,
- համար հեռացնելուց հետո,
- restore-ից հետո։

Այսինքն backup-ի վերջին `.json` տարբերակը մնում է Telegram-ում, ոչ թե միայն Railway-ի filesystem-ում։

### Նոր Railway account տեղափոխվելու քայլերը

1. Նոր Railway account-ում deploy արեք bot-ը։
2. Նոր deployment-ում դրեք նույն `OWNER_ID`-ը։
3. Նոր bot-ում բացեք `👑 Admin Panel` → `📤 Restore`։
4. Telegram-ում պահպանված վերջին `auto_backup_*.json` ֆայլը ուղարկեք նոր bot-ին։
5. Սեղմեք `✅ Հաստատել Restore`։
6. Հին users, numbers և orders տվյալները կվերականգնվեն։

Այսպիսով **Railway-ի ժամկետի ավարտը կամ նոր account տեղափոխվելը չի նշանակում, որ տվյալները կորում են**, քանի դեռ Telegram-ում պահված վերջին backup ֆայլը ունեք։

> Կարևոր․ backup-ը պահեք նաև ձեր սեփական անվտանգ տեղում։ `BOT_TOKEN` և backup JSON-ը ուրիշներին մի ուղարկեք։

---

# 7. Առաջին համարը ավելացնելը

Bot-ում `/start` արեք։

Քանի որ ձեր Telegram ID-ն հավասար է `OWNER_ID`-ին, կտեսնեք.

```text
👑 Admin Panel
```

Բացեք.

```text
➕ Ավելացնել համար
```

Գրեք միջազգային ձևաչափով, օրինակ.

```text
+374XXXXXXXX
```

Հետո bot-ը կխնդրի Stars գինը.

```text
100
```

Համարը կստեղծվի.

```text
status = available
owner_id = NULL
price_stars = 100
```

Այն անմիջապես կհայտնվի վաճառքի ցուցակում։

Նույն phone number-ը երկրորդ անգամ ավելացնել չի թույլատրվում։

---

# 8. Օգտատիրոջ գնում

Սովորական user-ը տեսնում է.

```text
📱 Գնել համար
📦 Իմ համարները
🧾 Իմ պատվերները
ℹ️ Օգնություն
```

«Գնել համար»-ում ցուցադրվում են միայն.

```text
status = available
```

համարները։

User-ը ընտրում է համարը և ստանում Telegram invoice։

Invoice-ը օգտագործում է.

```text
currency = XTR
provider_token = ""
```

Stars-ի պաշտոնական payment flow-ը.

```text
Invoice
↓
pre_checkout_query
↓
successful_payment
↓
Database sale
```

Միայն `successful_payment` update-ից հետո համարը դառնում է `sold`։

---

# 9. Ինչպես է payment-ը հաստատվում

Pre-checkout փուլում bot-ը ստուգում է.

- invoice payload
- order ID
- user ID
- number ID
- order status
- number availability
- currency = XTR
- վճարման գումարը

Դրանից հետո Telegram-ին ուղարկվում է `ok=True`։

Սա դեռ վերջնական վաճառք չէ։

Վերջնական վաճառքը կատարվում է միայն `successful_payment` update-ից հետո։

---

# 10. Duplicate payment protection

Յուրաքանչյուր հաջող վճարման համար Telegram-ը տալիս է.

```text
telegram_payment_charge_id
```

Database-ում այն պահվում է unique դաշտում։

Եթե նույն payment update-ը կրկին գա, այն չի ստեղծի երկրորդ order և չի վաճառի նույն համարը երկրորդ անգամ։

Բացի դրանից, number-ի `available → sold` փոփոխությունը կատարվում է SQLite transaction-ի ներսում atomic `UPDATE ... WHERE status='available'` գործողությամբ։

Եթե երկու գնորդ փորձում են նույն համարը վճարել գրեթե միաժամանակ, միայն առաջին հաջող transaction-ը կարող է այն վաճառել։

Եթե երկրորդի payment-ը արդեն հաջողվել է Telegram-ում, բայց number-ը race-ի պատճառով այլևս հասանելի չէ, bot-ը փորձում է Telegram-ի `refundStarPayment` մեթոդով վերադարձնել Stars-ը և order-ը նշում է `refunded`։

---

# 11. My Numbers

User-ը կարող է տեսնել միայն.

```text
owner_id = իր Telegram ID
```

համարները։

Ուրիշ user-ի համարները չեն ցուցադրվում։

---

# 12. My Orders

User-ը տեսնում է միայն իր orders-ը.

- Order ID
- Number
- Stars amount
- Purchase date
- Status

Possible statuses.

```text
pending
paid
refunded
cancelled
```

---

# 13. Admin Panel

Միայն `OWNER_ID` account-ը կարող է օգտագործել admin գործողությունները։

Admin Panel.

```text
📦 Բոլոր համարները
➕ Ավելացնել համար
🗑️ Հեռացնել համար
📊 Վիճակագրություն
💰 Վաճառված
⭐ Stars Statistics
📥 Backup
📤 Restore
```

Յուրաքանչյուր callback-ում նույնպես `OWNER_ID` ստուգվում է։ UI-ում admin button-ը չերևալը ինքնուրույն security mechanism չէ։

---

# 14. Statistics

Admin-ը տեսնում է.

```text
📱 Ընդհանուր համարներ
🟢 Ազատ համարներ
🔴 Վաճառված համարներ
🧾 Ընդհանուր պատվերներ
⭐ Ընդհանուր հաստատված Stars
```

Միայն `status='paid'` orders-ի գումարն է մտնում հաստատված Stars total-ի մեջ։

---

# 15. Stars Statistics

Ցուցադրվում են.

- ընդհանուր հաստատված Stars
- հաստատված orders
- վաճառված numbers
- վերջին վճարումները
- Order ID
- User ID
- Number ID
- Stars amount
- Payment status
- Date

---

# 16. Backup

Admin Panel → `📥 Backup`

Bot-ը ստեղծում է JSON backup և ուղարկում է այն միայն `OWNER_ID`-ին։

Backup-ը ներառում է.

- users
- numbers
- prices
- statuses
- ownership
- purchase dates
- orders
- payment charge IDs
- payment statuses
- timestamps

Օրինակ ֆայլ.

```text
backup_2026....json
```

---

# 17. Restore

Նոր deployment-ում.

1. Deploy արեք նույն code-ը։
2. Set արեք `BOT_TOKEN`։
3. Set արեք `OWNER_ID`։
4. Start արեք bot-ը։
5. Ձեր OWNER account-ից ուղարկեք backup `.json` ֆայլը bot-ին։

Bot-ը.

1. ստուգում է sender-ը
2. ստուգում է JSON-ը
3. ստուգում է schema version-ը
4. ստուգում է users/numbers/orders կապերը
5. ցույց է տալիս warning
6. պահանջում է confirmation
7. միայն հաստատումից հետո restore է անում

Restore-ը փոխարինում է ընթացիկ users/numbers/orders տվյալները backup-ի տվյալներով։

Եթե validation-ը ձախողվի, restore-ը չի սկսվում։

---

# 18. Նոր Railway project տեղափոխում

Հին project.

```text
OLD RAILWAY
↓
Admin Panel
↓
📥 Backup
↓
backup.json
```

Նոր project.

```text
NEW RAILWAY
↓
Deploy same code
↓
BOT_TOKEN
↓
OWNER_ID
↓
Start bot
↓
Send backup.json
↓
Confirm Restore
```

Դրանից հետո users, numbers և orders տվյալները վերականգնվում են։

Նոր Railway account-ին code-ը կապված չէ։

---

# 19. Օրինակ՝ ամբողջական օգտագործում

Admin.

```text
➕ Ավելացնել համար
↓
+XXX001
↓
100
```

Database.

```text
phone_number = +XXX001
price_stars = 100
status = available
owner_id = NULL
```

User.

```text
📱 Գնել համար
↓
+XXX001
↓
100 ⭐
↓
⭐ Վճարել Stars-ով
↓
Telegram payment UI
↓
Payment confirmation
```

Bot.

```text
order.status = paid
number.status = sold
number.owner_id = User Telegram ID
number.purchased_at = current UTC time
order.telegram_payment_id = Telegram charge ID
```

Այնուհետև.

```text
+XXX001
```

անհետանում է մյուս users-ի վաճառքի ցուցակից։

Գնորդը տեսնում է այն.

```text
📦 Իմ համարները
```

Admin-ը տեսնում է.

```text
💰 Վաճառված
📱 +XXX001
👤 Owner Telegram ID
⭐ 100
🔴 Sold
```

---

# 20. Անվտանգության կարևոր նշումներ

- BOT_TOKEN-ը երբեք source code-ում hard-code մի արեք։
- BOT_TOKEN-ը մի ուղարկեք ուրիշներին։
- OWNER_ID-ը environment variable-ում պահեք։
- Admin callback-ները server-side ստուգվում են։
- User-owned տվյալները query-ներում սահմանափակված են Telegram user ID-ով։
- Sold number-ը երկրորդ անգամ չի վաճառվում։
- Payment confirmation-ը հիմնված է Telegram-ի `successful_payment` update-ի վրա։
- `pre_checkout_query`-ը ինքնուրույն չի նշում վաճառքը որպես վերջնական։
- Duplicate payment charge ID-ները չեն կրկնվում։
- Payment race-ի դեպքում bot-ը փորձում է refund անել վճարումը։
- Logs-ում token-ը կամ backup content-ը չի տպվում։

Այս project-ը նախատեսված է միայն այն հեռախոսահամարների համար, որոնց վաճառքի և տրամադրման իրավունքը դուք օրինականորեն ունեք, և օգտագործում է Telegram-ի պաշտոնական payment մեխանիզմը։

---

# 21. Production խորհուրդ

Մինչև իրական վաճառք սկսելը փորձարկեք Telegram-ի Stars test environment-ը և համոզվեք, որ.

- invoice-ը ստեղծվում է
- pre-checkout-ը հաստատվում է
- successful payment-ը ստացվում է
- number-ը դառնում է sold
- duplicate update-ը չի կրկնում վաճառքը
- backup-ը ստեղծվում է
- restore-ը աշխատում է

Telegram-ի պաշտոնական փաստաթղթերում Stars-ի համար օգտագործվում է `XTR`, և digital goods/services invoice-ի provider token-ը դատարկ է։

---

Project-ը պատրաստ է Railway deployment-ի համար։
