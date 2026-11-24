# ShortFuse static preview

The repository root contains the generated site. GitHub Pages can serve it as plain HTML and CSS (`.nojekyll`); WordPress and Python are not needed to host it. The site uses root-relative URLs, so serve it at the root of an origin rather than under a preview subdirectory.

## Preview locally

From the repository root with Python 3.10 or newer:

```powershell
python -m http.server 8765 --bind 127.0.0.1
```

Open <http://127.0.0.1:8765/> and follow the links to the ChromeOS guide. Stop the server with Ctrl+C.

## Regenerate from the export

```powershell
python .\import_wordpress.py 'C:\path\to\export.xml' --fetch-assets
```

Keep the WXR export outside the repository: it may include author and commenter metadata. Use `--fetch-assets` only for image uploads cleared for reuse. Without it, the importer uses the already-bundled images. ZIP downloads are served from the `www.shortfuse.org` S3 bucket and are not stored in this repository. When regenerating against a newer export, review the diff and remove stale generated routes or uploads separately; the importer does not delete existing files.

## Migration review

- The preview contains 72 published posts, 6 pages, 92 attachment routes, 85 images, and 7 ZIP downloads. Images retain their original upload paths; ZIP links use direct HTTPS URLs in the `www.shortfuse.org` S3 bucket. The homepage uses a paginated masonry grid styled after the live Baskerville 2 theme, with three columns above 1040px, two through 1040px, and one through 600px. Without JavaScript it falls back to a regular grid. The banner and Roboto Slab font are served locally. The Baskerville 2 banner is CC0 1.0; Roboto Slab is distributed under its [Apache 2.0 license](assets/Roboto-Slab-LICENSE.txt). WordPress ads, subscriptions, and cookie overlays are not reproduced.
- One third-party image on Fusion Messenger is not included. See [the migration report](migration-report.txt) for affected URLs and outbound links that were not checked.
- The Contact page points readers to About instead of submitting the WordPress form. The 20 exported comment records were not copied; threaded comments, new commenting, category archives, feeds, search, and WordPress theme/widget behavior are not included.
- The broken link in Conversation UI (Sneak Peek) now points directly to Experimenting with landscape and UI changes. Before any cutover, check legacy aliases, archive/feed URLs, and old download links against the live site and decide which need redirects or replacements.

The static site is intended for `clshortfuse.github.io`. Changing the `shortfuse.org` custom domain or DNS is not part of this migration. Any DNS move needs separate approval and a record inventory that preserves Home Assistant, mail, verification records, and intentional wildcards. The reserved Agents gateway hostname is not a Pages destination.
