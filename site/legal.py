"""Starter legal pages required by lava.top (terms/offer, refund policy, privacy policy).

{seller_name}, {contact_email}, {seller_country} and {brand} are filled from Студия > Настройки.
These are templates, not legal advice: the owner should review them.
"""

TERMS = """Last updated: November 13, 2026

These terms are a public offer from {seller_name} ("we", "us"), the owner of the {brand} website, to anyone who buys a digital product on this site ("you"). By paying for a product you accept these terms.

**1. What we sell**

Digital guides about baby and toddler sleep, delivered as downloadable files. The product name, contents and price are shown on the product page before you pay.

**2. Price and payment**

Prices are shown in US dollars (USD) or euros (EUR). You choose the currency before paying. Payment is processed by our payment partner lava.top under its own [Terms of Service](https://lava.top/en/docs/terms/) and [Privacy Policy](https://lava.top/en/docs/policy/). We never see or store your card details. Your bank may charge its own fees for currency conversion.

**3. Delivery**

Right after a successful payment you receive a download link on the payment page and by email to the address you entered. If you don't get it within 24 hours, check your spam folder and then write to us at {contact_email}.

**4. License**

The guide is for your personal, non-commercial use. You may download it, read it on your devices and print it for your family. You may not resell it, share the file publicly, or publish its contents without our written permission.

**5. Not medical advice**

The guide shares general information about infant and toddler sleep. It is not medical advice and does not replace your pediatrician. Always talk to a doctor about your child's health, feeding and sleep. Results differ from child to child, and we do not promise a specific result.

**6. Refunds**

Refunds follow our [Refund Policy](/refund-policy).

**7. Liability**

We provide the guide as it is. As far as the law allows, our total liability for any claim connected with a purchase is limited to the amount you paid for it. Nothing in these terms limits your rights as a consumer under the law of your country.

**8. Donations**

Donations on the support page are voluntary gifts. You get no product in return, and donations are not refundable except for a clear payment error (for example, a duplicate charge).

**9. Changes and contact**

We may update these terms. The version published on the date of your purchase applies to that purchase.

Seller: {seller_name}, {seller_country}
Email: {contact_email}"""

REFUND = """Last updated: November 13, 2026

We want you to be happy with your guide. Here is how refunds work.

**Before you download**

If you have paid but have not downloaded the guide yet, you can ask for a full refund within 14 days of purchase. No reasons needed.

**After you download**

Our guides are digital files. Once you start the download, you get the full content right away, so we normally can't take it back. By completing the purchase you agree that the download starts immediately and that, for this reason, the 14-day right of withdrawal ends once the download has started (where your local law allows this).

We will still refund you in full if:

- you were charged twice for the same order;
- the file is damaged or won't open, and we can't send you a working copy within 3 business days;
- you did not receive the download link and we can't deliver the guide.

**How to ask for a refund**

Write to {contact_email} with the email you used for payment and the date of purchase. We answer within 3 business days.

**How long it takes**

Approved refunds go back to the original payment method through lava.top, usually within 5 to 10 business days. Your bank may take a little longer to show it.

**Donations**

Donations are voluntary and are not refunded, except for a payment error such as a duplicate charge."""

PRIVACY = """Last updated: November 13, 2026

This policy explains what personal data {seller_name} ("we") collects on the {brand} website, why, and what your rights are.

**Who is responsible**

{seller_name}, {seller_country}. Email: {contact_email}.

**What data we get and why**

- **Purchases and donations.** Payments are processed by lava.top. To complete your order, lava.top collects your email and payment details. We receive your email, the product, the amount and the date, so we can deliver the guide, answer your questions and handle refunds. We never receive your card number.
- **Messages.** If you email us or write to us on Instagram, we use what you send only to reply to you.
- **Technical data.** Our server keeps standard logs (IP address, browser, pages visited, time) for security and to fix errors. Logs are deleted after 30 days.

**Cookies and browser storage**

The site does not use advertising or analytics cookies. It remembers the currency you chose (USD or EUR) in your browser's local storage. The payment widget is provided by lava.top and may set its own cookies needed for payment. Fonts are loaded from Google Fonts, which means your browser connects to Google's servers.

**Legal basis**

We process data to perform our contract with you (delivering what you bought), to meet legal duties (accounting and tax records), and for our legitimate interest in keeping the site secure.

**Who we share data with**

Only with services that help us run the site: lava.top (payments), our hosting provider (server), and Google Fonts (font files). We don't sell your data.

**How long we keep it**

Purchase records are kept as long as tax and accounting laws require. Messages are kept as long as needed to help you. Server logs are kept for 30 days.

**Your rights**

You can ask us to show, correct or delete your data, to limit how we use it, or to send it to you in a common format. You can also object to processing and complain to your local data protection authority. Write to {contact_email}; we answer within 30 days.

**Children**

The site is for parents. We don't knowingly collect data from children.

**Changes**

If we change this policy, we'll update the date at the top."""


def text_block(title, body):
    return {"type": "text", "title": title, "body": body, "dark": False}


LEGAL_PAGES = [
    {"slug": "terms", "title": "Terms of Sale", "nav_label": "Terms",
     "description": "Terms of sale and public offer for Hush & Hold digital guides.",
     "blocks": [text_block("Terms of Sale", TERMS)]},
    {"slug": "refund-policy", "title": "Refund Policy", "nav_label": "Refunds",
     "description": "How refunds work for Hush & Hold digital guides.",
     "blocks": [text_block("Refund Policy", REFUND)]},
    {"slug": "privacy-policy", "title": "Privacy Policy", "nav_label": "Privacy",
     "description": "How Hush & Hold handles your personal data.",
     "blocks": [text_block("Privacy Policy", PRIVACY)]},
]
