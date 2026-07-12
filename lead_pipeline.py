from __future__ import annotations

import argparse
import html
import json
import os
import re
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

DEFAULT_CONFIG = {
    'min_rating': 4.2,
    'min_reviews': 10,
    'target_industries': ['barber', 'beauty_salon', 'car_repair', 'dentist', 'electrician', 'hair_care', 'home_goods_store', 'lawyer', 'locksmith', 'moving_company', 'painter', 'plumber', 'real_estate_agency', 'roofing_contractor', 'spa'],
    'exclude_if_has_website': True,
}

PLACES_URL = 'https://places.googleapis.com/v1/places:searchText'
PLACES_FIELD_MASK = ','.join([
    'places.id', 'places.displayName', 'places.formattedAddress',
    'places.nationalPhoneNumber', 'places.internationalPhoneNumber',
    'places.rating', 'places.userRatingCount', 'places.types',
    'places.websiteUri', 'places.businessStatus',
])


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding='utf-8'))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding='utf-8')


def slugify(value: str) -> str:
    return re.sub(r'[^a-z0-9]+', '-', value.lower()).strip('-')


def load_config(path: Path | None) -> dict[str, Any]:
    if path is None:
        return dict(DEFAULT_CONFIG)
    config = dict(DEFAULT_CONFIG)
    config.update(load_json(path))
    return config


def normalize_google_place(place: dict[str, Any]) -> dict[str, Any]:
    display_name = place.get('displayName') or {}
    return {
        'place_id': place.get('id') or '',
        'name': display_name.get('text') or '',
        'formatted_address': place.get('formattedAddress') or '',
        'formatted_phone_number': place.get('nationalPhoneNumber') or place.get('internationalPhoneNumber'),
        'rating': place.get('rating'),
        'user_ratings_total': place.get('userRatingCount'),
        'types': place.get('types') or [],
        'website': place.get('websiteUri'),
        'business_status': place.get('businessStatus'),
        'source_api': 'google_places_text_search_new',
        'source': place,
    }


def fetch_text_search(query: str, output_path: Path, api_key: str, included_type: str | None, page_size: int) -> list[dict[str, Any]]:
    payload: dict[str, Any] = {'textQuery': query, 'pageSize': page_size}
    if included_type:
        payload['includedType'] = included_type
        payload['strictTypeFiltering'] = True
    request = urllib.request.Request(
        PLACES_URL,
        data=json.dumps(payload).encode('utf-8'),
        method='POST',
        headers={'Content-Type': 'application/json', 'X-Goog-Api-Key': api_key, 'X-Goog-FieldMask': PLACES_FIELD_MASK},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            body = json.loads(response.read().decode('utf-8'))
    except urllib.error.HTTPError as error:
        detail = error.read().decode('utf-8', errors='replace')
        raise RuntimeError(f'Google Places request failed: HTTP {error.code} {detail}') from error
    places = [normalize_google_place(place) for place in body.get('places', []) if isinstance(place, dict)]
    write_json(output_path, places)
    return places


def has_website(place: dict[str, Any]) -> bool:
    website = place.get('website')
    return isinstance(website, str) and bool(website.strip())


def qualify_place(place: dict[str, Any], config: dict[str, Any]) -> dict[str, Any] | None:
    if place.get('business_status') not in (None, 'OPERATIONAL'):
        return None
    if config['exclude_if_has_website'] and has_website(place):
        return None
    rating = float(place.get('rating') or 0)
    reviews = int(place.get('user_ratings_total') or 0)
    if rating < float(config['min_rating']) or reviews < int(config['min_reviews']):
        return None
    place_types = list(place.get('types') or [])
    industries = [item for item in place_types if item in set(config['target_industries'])]
    if not industries:
        return None
    name = str(place.get('name') or 'Unknown Business')
    place_id = str(place.get('place_id') or slugify(name))
    lead_id = f'{slugify(name)}-{slugify(place_id)}'
    return {
        'lead_id': lead_id,
        'place_id': place_id,
        'name': name,
        'address': str(place.get('formatted_address') or place.get('vicinity') or ''),
        'phone': place.get('formatted_phone_number') or place.get('international_phone_number'),
        'rating': rating,
        'review_count': reviews,
        'industries': industries,
        'types': place_types,
        'website': place.get('website') or None,
    }


def brief_text(lead: dict[str, Any]) -> str:
    industry = ', '.join(lead['industries']).replace('_', ' ')
    phone = lead.get('phone') or 'No phone in source data'
    return '\n'.join([
        f'Business: {lead["name"]}',
        f'Address: {lead["address"]}',
        f'Phone: {phone}',
        f'Industry match: {industry}',
        f'Google rating: {lead["rating"]} from {lead["review_count"]} reviews',
        'Website: none found in Google Places source data',
        '',
        'Generation notes:',
        '- Build a simple, trustworthy local-business landing page.',
        '- Keep claims conservative unless source data supports them.',
        '- Mention the city/neighborhood if clear from the address.',
    ]) + '\n'


def qualify(input_path: Path, output_dir: Path, config_path: Path | None) -> list[dict[str, Any]]:
    config = load_config(config_path)
    raw_places = load_json(input_path)
    if not isinstance(raw_places, list):
        raise ValueError('Input must be a JSON array of Google Places result objects.')
    leads = [lead for place in raw_places if isinstance(place, dict) for lead in [qualify_place(place, config)] if lead]
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / 'qualified_leads.json', leads)
    for lead in leads:
        lead_dir = output_dir / lead['lead_id']
        write_json(lead_dir / 'lead.json', lead)
        write_json(lead_dir / 'status.json', {'lead_id': lead['lead_id'], 'status': 'qualified', 'site_generated': False, 'email_drafted': False, 'qa_passed': False, 'published': False, 'email_sent': False})
        write_text(lead_dir / 'brief.txt', brief_text(lead))
    return leads


def lead_dirs(leads_dir: Path, lead_id: str | None = None) -> list[Path]:
    if lead_id:
        target = leads_dir / lead_id
        if not target.exists():
            raise FileNotFoundError(f'Lead not found: {target}')
        return [target]
    return sorted(path for path in leads_dir.iterdir() if path.is_dir() and (path / 'lead.json').exists())


def city_from_address(address: str) -> str:
    parts = [part.strip() for part in address.split(',')]
    return parts[1] if len(parts) > 1 else 'your area'


def display_industry(lead: dict[str, Any]) -> str:
    return str((lead.get('industries') or lead.get('types') or ['local business'])[0]).replace('_', ' ')


def generation_prompt(lead: dict[str, Any], brief: str) -> str:
    return '\n'.join([
        'Create a simple static website and outreach email for this local business lead.',
        '',
        'Rules:',
        '- Do not invent awards, years in business, staff names, financing, or exact services.',
        '- Use only conservative claims supported by the lead brief.',
        '- Keep the page direct: hero, trust strip, services, reviews summary, contact section.',
        '- The email should be short, specific, and include a live demo URL placeholder.',
        '',
        'Lead JSON:',
        json.dumps(lead, indent=2, ensure_ascii=False),
        '',
        'Lead brief:',
        brief,
    ])


def local_copy(lead: dict[str, Any]) -> dict[str, Any]:
    name = lead['name']
    city = city_from_address(lead.get('address') or '')
    industry = display_industry(lead)
    rating = lead.get('rating', 'strong')
    reviews = lead.get('review_count', 'many')
    return {
        'headline': f'A cleaner first impression for {name}',
        'subheadline': f'{name} already has the trust signals people look for: a {rating} star Google rating across {reviews} reviews. This demo turns that credibility into a simple, mobile-friendly site for people searching in {city}.',
        'trust_items': [f'{rating} star Google rating', f'{reviews} Google reviews', f'Serving {city}'],
        'services': [f'{industry.title()} services', 'Local appointments and inquiries', 'Simple directions and click-to-call contact'],
        'review_summary': 'The source data shows strong customer feedback. The finished site should let that reputation do more work without making unsupported claims.',
        'contact_note': f'This demo uses the phone and address from Google Places so customers can reach {name} quickly.',
    }


def render_copy_txt(copy: dict[str, Any]) -> str:
    lines = [f'Headline: {copy["headline"]}', f'Subheadline: {copy["subheadline"]}', '', 'Trust items:']
    lines.extend(f'- {item}' for item in copy['trust_items'])
    lines.extend(['', 'Services:'])
    lines.extend(f'- {item}' for item in copy['services'])
    lines.extend(['', f'Review summary: {copy["review_summary"]}', f'Contact note: {copy["contact_note"]}'])
    return '\n'.join(lines) + '\n'


def render_email(lead: dict[str, Any]) -> str:
    name = lead['name']
    city = city_from_address(lead.get('address') or '')
    industry = display_industry(lead)
    return '\n'.join([
        f'Subject: quick demo site idea for {name}',
        '',
        f'Hi {name} team,',
        '',
        f'I noticed {name} has strong Google reviews but I did not find a website listed in Places.',
        f'I put together a simple demo page showing how a clean {industry} site could look for customers in {city}:',
        '',
        '{{LIVE_DEMO_URL}}',
        '',
        'No pressure if this is not useful. If you want it adjusted, I can tailor the copy, colors, and calls to action.',
        '',
        'Best,',
        '{{SENDER_NAME}}',
    ]) + '\n'


def render_index_html(lead: dict[str, Any], copy: dict[str, Any]) -> str:
    name = html.escape(lead['name'])
    phone = html.escape(lead.get('phone') or '')
    address = html.escape(lead.get('address') or '')
    phone_href = re.sub(r'[^0-9+]', '', lead.get('phone') or '')
    trust_items = '\n'.join(f'<li>{html.escape(item)}</li>' for item in copy['trust_items'])
    services = '\n'.join(f'<li>{html.escape(item)}</li>' for item in copy['services'])
    return f'''<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{name}</title>
  <meta name="description" content="{html.escape(copy['subheadline'])}">
  <link rel="stylesheet" href="styles.css">
</head>
<body>
  <header class="site-header"><a class="brand" href="#top">{name}</a><nav><a href="#services">Services</a><a href="#contact">Contact</a></nav></header>
  <main id="top">
    <section class="hero"><p class="eyebrow">Local business demo</p><h1>{html.escape(copy['headline'])}</h1><p class="lede">{html.escape(copy['subheadline'])}</p><div class="actions"><a class="button primary" href="tel:{phone_href}">Call now</a><a class="button secondary" href="#services">View services</a></div></section>
    <section class="trust"><ul>{trust_items}</ul></section>
    <section id="services" class="section"><div><p class="eyebrow">What customers need fast</p><h2>Clear reasons to choose {name}</h2></div><ul class="service-list">{services}</ul></section>
    <section class="section muted"><div><p class="eyebrow">Reputation</p><h2>Let the reviews work harder</h2></div><p>{html.escape(copy['review_summary'])}</p></section>
    <section id="contact" class="section contact"><div><p class="eyebrow">Contact</p><h2>Ready for a customer call</h2></div><address><strong>{name}</strong><br>{address}<br><a href="tel:{phone_href}">{phone}</a></address><p>{html.escape(copy['contact_note'])}</p></section>
  </main>
  <script src="script.js"></script>
</body>
</html>
'''


def render_styles_css() -> str:
    return '''*{box-sizing:border-box}html{scroll-behavior:smooth}body{margin:0;color:#17211d;background:#f7f4ee;font-family:Arial,Helvetica,sans-serif;line-height:1.5}a{color:inherit}.site-header{position:sticky;top:0;display:flex;align-items:center;justify-content:space-between;gap:24px;padding:18px clamp(18px,4vw,56px);background:rgba(247,244,238,.92);border-bottom:1px solid #ddd5c8;backdrop-filter:blur(10px)}.brand{font-weight:800;text-decoration:none}nav{display:flex;gap:18px;font-size:.95rem}nav a{text-decoration:none}.hero{min-height:68vh;display:grid;align-content:center;gap:20px;padding:clamp(48px,9vw,96px) clamp(18px,6vw,88px);background:linear-gradient(120deg,rgba(23,33,29,.88),rgba(49,82,85,.7)),url("https://images.unsplash.com/photo-1497366754035-f200968a6e72?auto=format&fit=crop&w=1600&q=80");background-position:center;background-size:cover;color:#fffdf8}.eyebrow{margin:0;color:#b9573f;font-weight:800;letter-spacing:0;text-transform:uppercase;font-size:.78rem}.hero .eyebrow{color:#ffd0a6}h1,h2,p{margin-top:0}h1{max-width:820px;margin-bottom:0;font-size:clamp(2.4rem,7vw,5.7rem);line-height:.98;letter-spacing:0}h2{margin-bottom:0;font-size:clamp(1.65rem,4vw,3rem);line-height:1.05;letter-spacing:0}.lede{max-width:760px;font-size:clamp(1.05rem,2vw,1.3rem)}.actions{display:flex;flex-wrap:wrap;gap:12px}.button{min-height:46px;display:inline-flex;align-items:center;justify-content:center;padding:12px 18px;border-radius:6px;font-weight:800;text-decoration:none}.primary{background:#f2b56b;color:#17211d}.secondary{border:1px solid rgba(255,255,255,.66)}.trust{padding:0 clamp(18px,6vw,88px);background:#315255;color:#fffdf8}.trust ul{max-width:1120px;margin:0 auto;padding:20px 0;display:grid;grid-template-columns:repeat(3,1fr);gap:16px;list-style:none}.trust li{font-weight:800}.section{max-width:1120px;margin:0 auto;padding:clamp(44px,7vw,78px) clamp(18px,4vw,32px);display:grid;grid-template-columns:minmax(0,.9fr) minmax(0,1.1fr);gap:clamp(28px,6vw,72px)}.muted{max-width:none;padding-left:max(clamp(18px,6vw,88px),calc((100vw - 1120px)/2));padding-right:max(clamp(18px,6vw,88px),calc((100vw - 1120px)/2));background:#e8dfd2}.service-list{margin:0;padding:0;display:grid;gap:12px;list-style:none}.service-list li{padding:18px;border-left:5px solid #b9573f;background:#fffdf8}address{font-style:normal}@media(max-width:760px){.site-header,.section{grid-template-columns:1fr}.site-header{align-items:flex-start;flex-direction:column}.trust ul{grid-template-columns:1fr}}'''


def generate_for_lead(lead_dir: Path, force: bool = False) -> dict[str, Path]:
    lead = load_json(lead_dir / 'lead.json')
    brief = (lead_dir / 'brief.txt').read_text(encoding='utf-8')
    site_dir = lead_dir / 'site'
    index_path = site_dir / 'index.html'
    if index_path.exists() and not force:
        return {'skipped': index_path}
    copy = local_copy(lead)
    write_text(lead_dir / 'generation_prompt.txt', generation_prompt(lead, brief))
    write_json(lead_dir / 'page_structure.json', {'lead_id': lead['lead_id'], 'pages': [{'path': 'index.html', 'sections': ['hero', 'trust', 'services', 'reputation', 'contact']}]})
    write_text(lead_dir / 'copy.txt', render_copy_txt(copy))
    write_text(lead_dir / 'email.txt', render_email(lead))
    write_text(index_path, render_index_html(lead, copy))
    write_text(site_dir / 'styles.css', render_styles_css())
    write_text(site_dir / 'script.js', 'document.documentElement.classList.add("js-ready");\n')
    write_json(lead_dir / 'status.json', {**load_json(lead_dir / 'status.json'), 'status': 'generated', 'site_generated': True, 'email_drafted': True, 'qa_passed': False})
    return {'generated': index_path}


def generate(leads_dir: Path, lead_id: str | None, force: bool) -> list[dict[str, Path]]:
    return [generate_for_lead(path, force) for path in lead_dirs(leads_dir, lead_id)]


def qa_for_lead(lead_dir: Path) -> dict[str, Any]:
    site_dir = lead_dir / 'site'
    index_path = site_dir / 'index.html'
    email_path = lead_dir / 'email.txt'
    lead = load_json(lead_dir / 'lead.json')
    html_content = index_path.read_text(encoding='utf-8') if index_path.exists() else ''
    checks = [
        {'name': 'index.html exists', 'passed': index_path.exists()},
        {'name': 'styles.css exists', 'passed': (site_dir / 'styles.css').exists()},
        {'name': 'script.js exists', 'passed': (site_dir / 'script.js').exists()},
        {'name': 'email.txt exists', 'passed': email_path.exists()},
        {'name': 'business name appears', 'passed': lead['name'] in html_content},
        {'name': 'viewport meta present', 'passed': 'name="viewport"' in html_content},
        {'name': 'no live URL placeholder in site', 'passed': '{{LIVE_DEMO_URL}}' not in html_content},
        {'name': 'email keeps live URL placeholder', 'passed': '{{LIVE_DEMO_URL}}' in email_path.read_text(encoding='utf-8') if email_path.exists() else False},
    ]
    passed = all(check['passed'] for check in checks)
    report = {'lead_id': lead['lead_id'], 'passed': passed, 'checks': checks}
    write_json(lead_dir / 'qa_report.json', report)
    write_text(lead_dir / 'qa_report.txt', '\n'.join([f'QA passed: {passed}', '', *[f'{"PASS" if c["passed"] else "FAIL"} - {c["name"]}' for c in checks], '']))
    write_json(lead_dir / 'status.json', {**load_json(lead_dir / 'status.json'), 'status': 'qa_passed' if passed else 'qa_failed', 'qa_passed': passed})
    return report


def qa(leads_dir: Path, lead_id: str | None) -> list[dict[str, Any]]:
    return [qa_for_lead(path) for path in lead_dirs(leads_dir, lead_id)]


def status_rows(leads_dir: Path) -> list[dict[str, Any]]:
    rows = []
    for path in lead_dirs(leads_dir):
        lead = load_json(path / 'lead.json')
        status = load_json(path / 'status.json') if (path / 'status.json').exists() else {}
        rows.append({'lead_id': lead['lead_id'], 'status': status.get('status', 'unknown'), 'site_generated': bool(status.get('site_generated')), 'email_drafted': bool(status.get('email_drafted')), 'qa_passed': bool(status.get('qa_passed')), 'published': bool(status.get('published')), 'email_sent': bool(status.get('email_sent'))})
    return rows


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description='Collect and qualify local business leads.')
    subparsers = parser.add_subparsers(dest='command', required=True)
    fetch_parser = subparsers.add_parser('fetch-text')
    fetch_parser.add_argument('--query', required=True)
    fetch_parser.add_argument('--included-type', default=None)
    fetch_parser.add_argument('--output', type=Path, default=Path('data/raw_places.json'))
    fetch_parser.add_argument('--page-size', type=int, default=20)
    fetch_parser.add_argument('--api-key-env', default='GOOGLE_PLACES_API_KEY')
    qualify_parser = subparsers.add_parser('qualify')
    qualify_parser.add_argument('--input', type=Path, required=True)
    qualify_parser.add_argument('--output', type=Path, default=Path('leads'))
    qualify_parser.add_argument('--config', type=Path, default=None)
    generate_parser = subparsers.add_parser('generate')
    generate_parser.add_argument('--leads-dir', type=Path, default=Path('leads'))
    generate_parser.add_argument('--lead-id', default=None)
    generate_parser.add_argument('--force', action='store_true')
    qa_parser = subparsers.add_parser('qa')
    qa_parser.add_argument('--leads-dir', type=Path, default=Path('leads'))
    qa_parser.add_argument('--lead-id', default=None)
    status_parser = subparsers.add_parser('status')
    status_parser.add_argument('--leads-dir', type=Path, default=Path('leads'))
    return parser


def main() -> None:
    args = build_parser().parse_args()
    if args.command == 'fetch-text':
        api_key = os.environ.get(args.api_key_env)
        if not api_key:
            raise SystemExit(f'Set {args.api_key_env} before fetching from Google Places.')
        places = fetch_text_search(args.query, args.output, api_key, args.included_type, args.page_size)
        print(f'Fetched {len(places)} place(s) -> {args.output}')
    elif args.command == 'qualify':
        leads = qualify(args.input, args.output, args.config)
        print(f'Qualified {len(leads)} lead(s).')
        for lead in leads:
            print(f'- {lead["name"]} -> {args.output / lead["lead_id"]}')
    elif args.command == 'generate':
        for result in generate(args.leads_dir, args.lead_id, args.force):
            label, path = next(iter(result.items()))
            print(f'{label}: {path}')
    elif args.command == 'qa':
        for report in qa(args.leads_dir, args.lead_id):
            print(f'{report["lead_id"]}: {"PASS" if report["passed"] else "FAIL"}')
    elif args.command == 'status':
        for row in status_rows(args.leads_dir):
            print(f'{row["lead_id"]} | {row["status"]} | site={row["site_generated"]} email={row["email_drafted"]} qa={row["qa_passed"]} published={row["published"]} sent={row["email_sent"]}')


if __name__ == '__main__':
    main()
