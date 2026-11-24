"""Build the static preview from a local WordPress WXR file (Python 3.10+)."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import date as calendar_date
from html import escape, unescape
from html.parser import HTMLParser
from pathlib import Path
import re
from urllib.parse import quote, unquote, urljoin, urlsplit, urlunsplit
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parent
CONTENT = '{http://purl.org/rss/1.0/modules/content/}encoded'
HOSTS = {'shortfuse.org', 'www.shortfuse.org', 'shortfuseorg.wordpress.com'}
DOWNLOAD_BASE_URL = 'https://s3.us-east-1.amazonaws.com/www.shortfuse.org'
ASSETS = {
    '.png': ('image/png', b'\x89PNG\r\n\x1a\n', 20 * 1024 * 1024),
    '.jpg': ('image/jpeg', b'\xff\xd8\xff', 20 * 1024 * 1024),
    '.jpeg': ('image/jpeg', b'\xff\xd8\xff', 20 * 1024 * 1024),
}
IMAGES = set(ASSETS)
DOWNLOADS = {'.zip'}


def field(item, name):
    return item.findtext('{*}' + name, '')


def route(url):
    return quote(unquote(urlsplit(url).path).rstrip('/') + '/', safe='/')


def destination(path):
    parts = unquote(path).strip('/').split('/') if path != '/' else []
    if any(not part or part in {'.', '..'} or re.search(r'[:\\\x00]', part) for part in parts):
        raise ValueError(f'Unsafe path: {path}')
    return ROOT.joinpath(*parts)


def asset_path(url):
    u = urlsplit(url)
    if (u.hostname in HOSTS | {'shortfuseorg.files.wordpress.com'}
            and (u.path.startswith('/wp-content/uploads/') or u.hostname == 'shortfuseorg.files.wordpress.com')):
        path = '/wp-content/uploads/' + u.path.removeprefix('/wp-content/uploads/').lstrip('/')
        if Path(path).suffix.lower() in IMAGES | DOWNLOADS:
            return path
    return None


def fetch_asset(entry):
    path, url = entry
    target = destination(path)
    if target.is_file():
        return path, None
    try:
        expected, signature, maximum = ASSETS[target.suffix.lower()]
        request = Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urlopen(request, timeout=30) as response:
            data = response.read(maximum + 1)
            if response.headers.get_content_type() != expected or not data.startswith(signature) or len(data) > maximum:
                raise ValueError('unexpected asset format or size')
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        return path, None
    except (OSError, ValueError) as error:
        return path, str(error)


class ContentLinks(HTMLParser):
    def __init__(self, source, routes, ids, media, issues, external):
        super().__init__(convert_charrefs=False)
        self.source, self.routes, self.ids = source, routes, ids
        self.media, self.issues, self.external = media, issues, external
        self.output = []

    def handle_starttag(self, tag, attrs):
        updated = []
        for name, value in attrs:
            if name in {'href', 'src'} and value and not value.startswith('#'):
                if tag == 'img' and value.startswith('data:'):
                    continue
                absolute = urljoin('https://shortfuse.org' + self.source, value)
                u = urlsplit(absolute)
                local = asset_path(absolute)
                if local and Path(local).suffix.lower() in DOWNLOADS:
                    value = DOWNLOAD_BASE_URL + quote(unquote(local), safe='/')
                    if u.fragment:
                        value += '#' + u.fragment
                elif local in self.media:
                    value = quote(unquote(local), safe='/') + ('#' + u.fragment if u.fragment else '')
                elif name == 'src' and tag == 'img':
                    self.issues.add((self.source, 'Image not bundled', absolute))
                    continue
                elif u.hostname in HOSTS:
                    post_id = re.fullmatch(r'(?:p|page_id|attachment_id)=(\d+)', u.query)
                    target = self.ids.get(post_id[1]) if post_id else route(absolute)
                    if self.source == '/2013/02/24/conversation-ui-sneak-peek/' and target == '/2017/06/15/161/':
                        target = '/2013/02/26/experimenting-with-landscape-and-ui-changes/'
                    if target in self.routes:
                        value = urlunsplit(('', '', target, '' if post_id else u.query, u.fragment))
                    else:
                        self.issues.add((self.source, 'Internal URL not migrated', absolute))
                        value = absolute
                elif u.scheme in {'http', 'https'}:
                    self.external.add((self.source, absolute))
                elif u.scheme not in {'mailto', 'tel'}:
                    continue
            if name.startswith('on') or name in {'srcset', 'style'}:
                continue
            updated.append(' ' + name + ('' if value is None else '="' + escape(value, quote=True) + '"'))
        self.output.append('<' + tag + ''.join(updated) + '>')

    handle_startendtag = handle_starttag

    def handle_endtag(self, tag):
        self.output.append(f'</{tag}>')

    def handle_data(self, data):
        self.output.append(data)

    def handle_entityref(self, name):
        self.output.append(f'&{name};')

    def handle_charref(self, name):
        self.output.append(f'&#{name};')


def paragraphs(text):
    blocks = r'(pre|p|div|table|ul|ol|h[1-6]|blockquote)'
    parts = re.split(fr'(<{blocks}(?:\s[^>]*)?>[\s\S]*?</\2\s*>)', text, flags=re.I)
    output = []
    for index, part in enumerate(parts):
        if index % 3 == 1:
            output.append(part)
        elif index % 3 == 0:
            output.extend('<p>' + para.strip().replace('\n', '<br>\n') + '</p>'
                          for para in re.split(r'\n[ \t]*\n+', part) if para.strip())
    return '\n'.join(output)


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument('export', type=Path)
    cli.add_argument('--fetch-assets', '--fetch-images', dest='fetch_assets', action='store_true',
                     help='Download rights-cleared exported uploads')
    args = cli.parse_args()
    channel = ET.parse(args.export).find('channel')
    items = channel.findall('item')
    published = [i for i in items if field(i, 'status') == 'publish' and field(i, 'post_type') in {'post', 'page'}]
    posts = sorted((i for i in published if field(i, 'post_type') == 'post'),
                   key=lambda i: field(i, 'post_date'), reverse=True)
    pages = [i for i in published if field(i, 'post_type') == 'page']
    attachments = [i for i in items if field(i, 'post_type') == 'attachment']
    paths = {i: route(i.findtext('link')) for i in published + attachments}
    if len(set(paths.values())) != len(paths) or '/' in paths.values():
        raise ValueError('Conflicting exported permalinks')
    ids = {field(i, 'post_id'): path for i, path in paths.items()}
    assets = {path: url for i in attachments
              if (url := field(i, 'attachment_url'))
              and (path := asset_path(url))
              and Path(path).suffix.lower() in IMAGES}
    downloads = {path: url for i in attachments
                 if (url := field(i, 'attachment_url'))
                 and (path := asset_path(url))
                 and Path(path).suffix.lower() in DOWNLOADS}
    if args.fetch_assets:
        with ThreadPoolExecutor(max_workers=10) as executor:
            results = dict(executor.map(fetch_asset, assets.items()))
    else:
        results = {path: None if destination(path).is_file() else 'not downloaded' for path in assets}
    bundled = {path for path, error in results.items() if error is None}
    issues, external = set(), set()
    for path, error in results.items():
        if error:
            issues.add((path, 'Upload unavailable', assets[path] + ' (' + error + ')'))

    def title(i):
        return escape(unescape(i.findtext('title', '')))

    def anchor(i):
        return f'<a href="{paths[i]}">{title(i)}</a>'

    menu_order = ('/oreocolorizer/', '/fusion-messenger/', '/superoneclick/', '/about/', '/donate/')
    page_by_path = {paths[i]: i for i in pages}
    nav = ''.join(f'<li>{link}</li>' for link in ['<a href="/">Home</a>']
                  + [anchor(page_by_path[p]) for p in menu_order if p in page_by_path])

    def write(path, name, body, layout='single'):
        target = destination(path) / 'index.html'
        target.parent.mkdir(parents=True, exist_ok=True)
        script = '<script src="/masonry.js" defer></script>' if layout == 'archive' else ''
        body = re.sub(r'[ \t]+(?=\n)', '', body)
        target.write_text(f'''<!doctype html>
<html lang="en">
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{name}</title>
<link rel="stylesheet" href="/site.css">
{script}
<body id="top">
<a class="skip" href="#content">Skip to content</a>
<header class="masthead">
<a class="site-title" href="/">shortfuse.org</a>
<div class="social"><a href="https://github.com/clshortfuse/">GitHub</a> <a href="https://twitter.com/clshortfuse">Twitter</a></div>
</header>
<nav class="main-nav" aria-label="Main navigation"><ul>{nav}</ul></nav>
<main id="content" class="{layout}">{body}</main>
<footer><a href="/contact/">Contact</a> <a href="#top">Up ↑</a></footer>
</body>
</html>
''', encoding='utf-8')

    def date(i):
        value = field(i, 'post_date')[:10]
        day = calendar_date.fromisoformat(value)
        return f'<time datetime="{value}">{day:%B} {day.day}, {day.year}</time>'

    covers = dict(enumerate((None, '01-setupsecureshell.png', '11-bashrcremounthome.png',
                            '15-installnvm.png', '27-opennewsecureshellwindow.png',
                            '67-manageandroidpreference.png'), 1))

    def card(i):
        path = paths[i]
        part = re.fullmatch(r'/2017/06/15/guide-developing-on-chromeos-part-([1-6])/', path)
        cover = covers.get(int(part[1])) if part else None
        image = f'/wp-content/uploads/2017/06/{cover}'
        picture = f'<a href="{path}" aria-hidden="true" tabindex="-1"><img src="{image}" alt=""></a>' if image in bundled else ''
        summary = i.findtext('{http://wordpress.org/export/1.2/excerpt/}encoded', '').strip()
        if not summary:
            text = re.sub(r'<[^>]+>', ' ', i.findtext(CONTENT, '').split('<!--more-->')[0])
            summary = ' '.join(unescape(text).split())
        heading = f'<h2>{anchor(i)}</h2>' if title(i) else ''
        timestamp = date(i) if heading else f'<a href="{path}">{date(i)}</a>'
        return f'<article class="card">{heading}{picture}<p><span class="card-excerpt">{escape(summary)}</span></p>{timestamp}</article>'

    def archive_path(n):
        return '/' if n == 0 else f'/page/{n + 1}/'

    routes = set(paths.values()) | {'/'}
    for n, start in enumerate(range(0, len(posts), 10)):
        links = []
        if n:
            links.append(f'<a href="{archive_path(n - 1)}">← Newer posts</a>')
        if start + 10 < len(posts):
            links.append(f'<a href="{archive_path(n + 1)}">Older posts →</a>')
        pagination = '<nav class="pagination" aria-label="Post pages">' + ' '.join(links) + '</nav>'
        write(archive_path(n), 'shortfuse.org', ''.join(card(i) for i in posts[start:start + 10]) + pagination, 'archive')
    for i in published:
        path = paths[i]
        text = i.findtext(CONTENT, '')
        if '[contact-form]' in text:
            text = re.sub(r'\[contact-form\].*?\[/contact-form\]',
                          '\n\nThe contact form is not available on this site. See the <a href="/about/">About page</a> for contact information.', text, flags=re.S)
        parser = ContentLinks(path, routes, ids, bundled, issues, external)
        parser.feed(paragraphs(text))
        parser.close()
        name = title(i)
        heading = f'<h1>{name}</h1>' if name else ''
        write(path, name or 'shortfuse.org', f'<article>{heading}{date(i)}\n' + ''.join(parser.output) + '</article>')
    for i in attachments:
        url = field(i, 'attachment_url')
        local = asset_path(url)
        if local in bundled and Path(local).suffix.lower() in IMAGES:
            src = escape(quote(unquote(local), safe='/'), quote=True)
            body = f'<a href="{src}"><img src="{src}" alt="{title(i)}"></a>'
        elif local and Path(local).suffix.lower() in DOWNLOADS:
            src = escape(DOWNLOAD_BASE_URL + quote(unquote(local), safe='/'), quote=True)
            body = f'<p><a href="{src}" download>Download {title(i) or Path(local).name}</a></p>'
        else:
            body = '<p>This attachment is not included in the preview.</p>'
            issues.add((paths[i], 'Attachment file not bundled', url))
        write(paths[i], title(i), f'<h1>{title(i)}</h1>{body}')

    image_count = sum(Path(path).suffix.lower() in IMAGES for path in bundled)
    download_count = len(downloads)
    counts = (f'{len(posts)} posts, {len(pages)} pages, {len(attachments)} attachment routes, '
              f'{image_count} local images, {download_count} S3 downloads')
    report = [counts, '', 'Internal URL and media exceptions (source | issue | URL):']
    report.extend(' | '.join(row) for row in sorted(issues))
    report.extend(['', 'External links retained but not checked (source | URL):'])
    report.extend(' | '.join(row) for row in sorted(external))
    (ROOT / 'migration-report.txt').write_text('\n'.join(report) + '\n', encoding='utf-8')
    print(counts)


if __name__ == '__main__':
    main()
