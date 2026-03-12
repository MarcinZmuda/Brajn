"""
===============================================================================
🚫 WEB GARBAGE FILTER v1.0 — Filtr CSS/JS/HTML artefaktów z encji
===============================================================================
Auto-generowana mega-blacklista na podstawie:
1. Pełna specyfikacja CSS (properties, values, pseudo-classes, functions)
2. Pełna lista HTML tagów + atrybutów
3. JavaScript keywords + DOM API
4. WordPress/Astra/Elementor/Divi class patterns
5. Bootstrap/Tailwind utility classes
6. YouTube/Google/Facebook JS internals
7. Cookie banners, analytics, tracking

Zamiast ręcznego utrzymywania listy — pattern-based + dictionary approach.

Autor: BRAJEN Team
Data: 2025
===============================================================================
"""

import re
from typing import Set

# ================================================================
# 📋 CSS — Properties (ALL from MDN Web Docs)
# ================================================================

_CSS_PROPERTIES = {
    # Box Model
    "margin", "padding", "border", "width", "height", "max-width", "min-width",
    "max-height", "min-height", "box-sizing", "overflow", "overflow-x", "overflow-y",
    
    # Display & Layout
    "display", "position", "top", "right", "bottom", "left", "float", "clear",
    "z-index", "visibility", "opacity", "clip", "clip-path",
    
    # Flexbox
    "flex", "flex-direction", "flex-wrap", "flex-flow", "flex-grow", "flex-shrink",
    "flex-basis", "justify-content", "align-items", "align-self", "align-content",
    "order", "gap", "row-gap", "column-gap",
    
    # Grid
    "grid", "grid-template", "grid-template-columns", "grid-template-rows",
    "grid-template-areas", "grid-area", "grid-column", "grid-row",
    "grid-auto-columns", "grid-auto-rows", "grid-auto-flow",
    "grid-column-start", "grid-column-end", "grid-row-start", "grid-row-end",
    
    # Typography
    "font", "font-family", "font-size", "font-weight", "font-style",
    "font-variant", "font-stretch", "line-height", "letter-spacing",
    "word-spacing", "text-align", "text-decoration", "text-transform",
    "text-indent", "text-shadow", "text-overflow", "white-space",
    "word-break", "word-wrap", "overflow-wrap", "hyphens",
    "font-feature-settings", "font-kerning", "font-display",
    
    # Color & Background
    "color", "background", "background-color", "background-image",
    "background-position", "background-size", "background-repeat",
    "background-attachment", "background-clip", "background-origin",
    "background-blend-mode",
    
    # Border & Outline
    "border-width", "border-style", "border-color", "border-radius",
    "border-top", "border-right", "border-bottom", "border-left",
    "border-collapse", "border-spacing", "border-image",
    "outline", "outline-width", "outline-style", "outline-color", "outline-offset",
    
    # Transform & Animation
    "transform", "transform-origin", "transform-style",
    "transition", "transition-property", "transition-duration",
    "transition-timing-function", "transition-delay",
    "animation", "animation-name", "animation-duration", "animation-delay",
    "animation-direction", "animation-fill-mode", "animation-iteration-count",
    "animation-play-state", "animation-timing-function",
    "perspective", "perspective-origin", "backface-visibility",
    
    # Filters & Effects
    "filter", "backdrop-filter", "mix-blend-mode", "isolation",
    "box-shadow", "object-fit", "object-position",
    
    # Table
    "table-layout", "caption-side", "empty-cells",
    
    # List
    "list-style", "list-style-type", "list-style-position", "list-style-image",
    
    # Scroll
    "scroll-behavior", "scroll-snap-type", "scroll-snap-align",
    "scroll-margin", "scroll-padding", "overscroll-behavior",
    
    # Misc
    "cursor", "pointer-events", "user-select", "resize", "appearance",
    "content", "counter-reset", "counter-increment", "quotes",
    "will-change", "contain", "aspect-ratio", "accent-color",
    "caret-color", "touch-action", "writing-mode", "direction",
    "unicode-bidi", "columns", "column-count", "column-width",
    "column-gap", "column-rule", "column-span", "page-break-before",
    "page-break-after", "page-break-inside", "orphans", "widows",
    "all", "initial", "unset", "revert",
}

# ================================================================
# 📋 CSS — Values & Keywords
# ================================================================

_CSS_VALUES = {
    # Display values
    "none", "block", "inline", "inline-block", "flex", "inline-flex",
    "grid", "inline-grid", "table", "table-row", "table-cell",
    "table-column", "list-item", "contents", "flow-root",
    
    # Position values
    "static", "relative", "absolute", "fixed", "sticky",
    
    # Common values
    "auto", "inherit", "initial", "unset", "revert", "normal",
    "transparent", "currentcolor", "currentColor",
    
    # Font weights
    "bold", "bolder", "lighter",
    
    # Font styles
    "italic", "oblique",
    
    # Text transform
    "uppercase", "lowercase", "capitalize",
    
    # Text align
    "center", "justify",
    
    # Text decoration
    "underline", "overline", "line-through", "wavy",
    
    # Overflow
    "hidden", "scroll", "visible", "clip",
    
    # Flexbox values
    "nowrap", "wrap", "wrap-reverse",
    "flex-start", "flex-end", "space-between", "space-around", "space-evenly",
    "stretch", "baseline",
    
    # Border styles
    "solid", "dashed", "dotted", "double", "groove", "ridge", "inset", "outset",
    
    # Cursor values
    "pointer", "default", "crosshair", "move", "text", "wait", "help",
    "not-allowed", "grab", "grabbing", "zoom-in", "zoom-out",
    
    # Background values
    "cover", "contain", "no-repeat", "repeat", "repeat-x", "repeat-y",
    "center", "top", "bottom", "left", "right",
    "fixed", "scroll", "local",
    
    # List style
    "disc", "circle", "square", "decimal", "lower-alpha", "upper-alpha",
    "lower-roman", "upper-roman",
    
    # Box sizing
    "border-box", "content-box",
    
    # Float
    "left", "right", "both",
    
    # Misc values
    "collapse", "separate", "break-all", "keep-all", "break-word",
    "pre", "pre-wrap", "pre-line",
    "ease", "ease-in", "ease-out", "ease-in-out", "linear",
    "forwards", "backwards", "alternate", "infinite",
    "ltr", "rtl",
}

# ================================================================
# 📋 CSS — Pseudo-classes & Pseudo-elements
# ================================================================

_CSS_PSEUDO = {
    "hover", "focus", "active", "visited", "link", "checked", "disabled",
    "enabled", "first-child", "last-child", "nth-child", "nth-of-type",
    "first-of-type", "last-of-type", "only-child", "only-of-type",
    "empty", "root", "target", "not", "lang", "where", "is", "has",
    "focus-within", "focus-visible", "placeholder-shown", "default",
    "valid", "invalid", "required", "optional", "read-only", "read-write",
    "in-range", "out-of-range", "indeterminate",
    "before", "after", "first-line", "first-letter", "selection",
    "placeholder", "marker", "backdrop",
}

# ================================================================
# 📋 CSS — Functions
# ================================================================

_CSS_FUNCTIONS = {
    "var", "calc", "rgb", "rgba", "hsl", "hsla", "url", "attr",
    "counter", "counters", "linear-gradient", "radial-gradient",
    "conic-gradient", "repeating-linear-gradient", "repeating-radial-gradient",
    "min", "max", "clamp", "minmax", "fit-content", "repeat",
    "translate", "translatex", "translatey", "translatez",
    "rotate", "rotatex", "rotatey", "rotatez",
    "scale", "scalex", "scaley", "scalez",
    "skew", "skewx", "skewy", "matrix", "matrix3d",
    "perspective", "blur", "brightness", "contrast", "grayscale",
    "hue-rotate", "invert", "saturate", "sepia", "drop-shadow",
    "cubic-bezier", "steps", "env", "format",
}

# ================================================================
# 📋 CSS — Units
# ================================================================

_CSS_UNITS = {
    "px", "em", "rem", "vh", "vw", "vmin", "vmax",
    "pt", "pc", "cm", "mm", "in", "ex", "ch",
    "fr", "deg", "rad", "turn", "grad",
    "ms", "dpi", "dpcm", "dppx",
}

# ================================================================
# 📋 HTML — Tags (ALL standard tags)
# ================================================================

_HTML_TAGS = {
    # Document
    "html", "head", "body", "doctype",
    
    # Metadata
    "meta", "title", "link", "style", "script", "noscript", "base",
    
    # Sections
    "header", "footer", "nav", "main", "section", "article", "aside",
    "address", "hgroup",
    
    # Content
    "div", "span", "p", "br", "hr", "pre", "blockquote",
    "ol", "ul", "li", "dl", "dt", "dd",
    "figure", "figcaption", "details", "summary", "dialog",
    
    # Headings
    "h1", "h2", "h3", "h4", "h5", "h6",
    
    # Inline text
    "a", "em", "strong", "small", "s", "cite", "q", "dfn",
    "abbr", "ruby", "rt", "rp", "data", "time", "code", "var",
    "samp", "kbd", "sub", "sup", "i", "b", "u", "mark", "bdi", "bdo",
    "wbr",
    
    # Media
    "img", "picture", "source", "audio", "video", "track",
    "iframe", "embed", "object", "param", "canvas", "map", "area",
    "svg", "math",
    
    # Table
    "table", "caption", "colgroup", "col", "thead", "tbody", "tfoot",
    "tr", "td", "th",
    
    # Forms
    "form", "fieldset", "legend", "label", "input", "button",
    "select", "datalist", "optgroup", "option", "textarea",
    "output", "progress", "meter",
    
    # Interactive
    "menu", "menuitem", "template", "slot",
}

# ================================================================
# 📋 HTML — Global Attributes
# ================================================================

_HTML_ATTRIBUTES = {
    "id", "class", "style", "title", "lang", "dir", "hidden",
    "tabindex", "accesskey", "contenteditable", "draggable",
    "spellcheck", "translate", "autofocus", "disabled", "readonly",
    "required", "placeholder", "pattern", "maxlength", "minlength",
    "autocomplete", "novalidate", "formaction", "formmethod",
    "name", "value", "type", "href", "src", "alt", "width", "height",
    "action", "method", "target", "rel", "media", "charset",
    "async", "defer", "crossorigin", "integrity", "loading",
    "srcset", "sizes", "decoding", "fetchpriority",
    "role", "aria", "data",
}

# ================================================================
# 📋 JavaScript — Keywords & DOM API
# ================================================================

_JS_KEYWORDS = {
    # Language keywords
    "var", "let", "const", "function", "return", "if", "else",
    "for", "while", "do", "switch", "case", "break", "continue",
    "try", "catch", "finally", "throw", "new", "delete", "typeof",
    "instanceof", "void", "this", "class", "extends", "super",
    "import", "export", "default", "from", "async", "await",
    "yield", "true", "false", "null", "undefined", "NaN", "Infinity",
    
    # DOM methods/properties
    "document", "window", "element", "node", "event", "listener",
    "querySelector", "querySelectorAll", "getElementById", "getElementsByClassName",
    "addEventListener", "removeEventListener", "appendChild", "removeChild",
    "innerHTML", "outerHTML", "textContent", "innerText",
    "getAttribute", "setAttribute", "classList", "dataset",
    "createElement", "createTextNode", "cloneNode",
    "parentNode", "childNodes", "firstChild", "lastChild",
    "nextSibling", "previousSibling", "parentElement",
    "offsetWidth", "offsetHeight", "offsetTop", "offsetLeft",
    "scrollTop", "scrollLeft", "scrollWidth", "scrollHeight",
    "clientWidth", "clientHeight", "clientTop", "clientLeft",
    "getBoundingClientRect", "getComputedStyle",
    "requestAnimationFrame", "setTimeout", "setInterval",
    "clearTimeout", "clearInterval",
    "console", "log", "warn", "error", "debug", "info",
    "prototype", "constructor", "toString", "valueOf",
    "stringify", "parse", "fetch", "then", "catch", "finally",
    "Promise", "resolve", "reject", "all", "race", "any",
    "Object", "Array", "String", "Number", "Boolean", "Symbol",
    "Map", "Set", "WeakMap", "WeakSet", "Proxy", "Reflect",
    "JSON", "Math", "Date", "RegExp", "Error",
    "push", "pop", "shift", "unshift", "splice", "slice",
    "map", "filter", "reduce", "forEach", "find", "findIndex",
    "includes", "indexOf", "join", "sort", "reverse",
    "keys", "values", "entries", "assign", "freeze",
    "length", "size", "count",
    
    # Events
    "onclick", "onload", "onchange", "onsubmit", "onkeydown", "onkeyup",
    "onmouseover", "onmouseout", "onmousedown", "onmouseup",
    "onfocus", "onblur", "oninput", "onscroll", "onresize",
    "touchstart", "touchend", "touchmove",
    
    # Browser APIs
    "localStorage", "sessionStorage", "cookie", "cookies",
    "navigator", "location", "history",
    "XMLHttpRequest", "FormData", "URLSearchParams",
    "Worker", "ServiceWorker", "WebSocket",
    "IntersectionObserver", "MutationObserver", "ResizeObserver",
    "Performance", "PerformanceObserver",
    "MediaQueryList", "matchMedia",
    "Notification", "geolocation",
    "requestIdleCallback", "postMessage",
    "AbortController", "AbortSignal",
}

# ================================================================
# 📋 WordPress / Astra / Elementor / Divi
# ================================================================

_WORDPRESS_PATTERNS = {
    # WordPress core
    "wp-block", "wp-element", "wp-image", "wp-post", "wp-admin",
    "wp-content", "wp-includes", "wp-json", "wp-embed",
    "entry-content", "entry-meta", "entry-header", "entry-footer",
    "entry-title", "entry-summary", "post-content", "post-meta",
    "post-thumbnail", "post-navigation", "comment-form",
    "comment-list", "comment-body", "comment-meta",
    "widget", "widget-area", "widget-title", "sidebar",
    "site-header", "site-footer", "site-content", "site-main",
    "site-navigation", "site-branding", "site-title", "site-description",
    "menu-item", "menu-toggle", "sub-menu", "primary-menu",
    "page-header", "page-content", "page-template",
    "archive", "archive-title", "archive-description",
    "search-form", "search-field", "search-submit",
    "pagination", "nav-links", "page-numbers",
    "alignwide", "alignfull", "aligncenter", "alignleft", "alignright",
    "has-text-align", "has-background", "has-text-color",
    "screen-reader-text", "skip-link",
    "woocommerce", "product", "cart", "checkout",
    
    # Astra theme (WP)
    "ast-container", "ast-header", "ast-footer", "ast-above-header",
    "ast-below-header", "ast-primary-header", "ast-mobile-header",
    "ast-site-identity", "ast-button", "ast-custom-button",
    "ast-global-color", "ast-comment", "ast-archive",
    "ast-single-post", "ast-page", "ast-404",
    "ast-separate-container", "ast-plain-container",
    "ast-breadcrumbs", "ast-woocommerce",
    "ast-no-sidebar", "ast-left-sidebar", "ast-right-sidebar",
    "ast-above-header-bar", "ast-below-header-bar",
    "ast-mobile-popup", "ast-search-menu",
    "ast-header-break-point", "ast-mobile-menu",
    "ast-main-header-wrap", "ast-mobile-header-wrap",
    "ast-flex", "ast-grid", "ast-row",
    "ast-orders-table", "ast-cart-drawer",
    
    # Elementor
    "elementor", "elementor-widget", "elementor-element",
    "elementor-column", "elementor-row", "elementor-section",
    "elementor-container", "elementor-inner", "elementor-button",
    "elementor-heading", "elementor-text-editor", "elementor-image",
    "elementor-icon", "elementor-spacer", "elementor-divider",
    "elementor-accordion", "elementor-tabs", "elementor-toggle",
    "elementor-counter", "elementor-progress-bar",
    "elementor-testimonial", "elementor-carousel",
    "elementor-popup", "elementor-motion-effects",
    "elementor-background-overlay", "elementor-shape-fill",
    "elementor-kit", "elementor-location",
    "ekit", "e-parent", "e-child", "e-con",
    
    # Divi
    "et-pb", "et_pb", "et-boc", "et-l",
    "et_pb_module", "et_pb_row", "et_pb_section", "et_pb_column",
    "et_pb_text", "et_pb_image", "et_pb_button", "et_pb_slider",
    "et_pb_blurb", "et_pb_cta", "et_pb_testimonial",
    "et_pb_toggle", "et_pb_accordion", "et_pb_tabs",
    "et_builder", "et_overlay", "et_bloom", "et_monarch",
}

# ================================================================
# 📋 Bootstrap / Tailwind / Foundation
# ================================================================

_CSS_FRAMEWORKS = {
    # Bootstrap classes
    "container", "container-fluid", "container-sm", "container-md",
    "container-lg", "container-xl", "container-xxl",
    "row", "col", "col-sm", "col-md", "col-lg", "col-xl", "col-xxl",
    "btn", "btn-primary", "btn-secondary", "btn-success", "btn-danger",
    "btn-warning", "btn-info", "btn-light", "btn-dark", "btn-outline",
    "navbar", "navbar-brand", "navbar-nav", "navbar-toggler",
    "nav-item", "nav-link", "dropdown", "dropdown-menu", "dropdown-item",
    "card", "card-body", "card-header", "card-footer", "card-title",
    "modal", "modal-dialog", "modal-content", "modal-header", "modal-body",
    "carousel", "carousel-item", "carousel-control",
    "accordion", "accordion-item", "accordion-header", "accordion-body",
    "badge", "alert", "toast", "tooltip", "popover",
    "breadcrumb", "breadcrumb-item", "pagination", "page-item", "page-link",
    "form-control", "form-group", "form-label", "form-check",
    "input-group", "form-select", "form-floating",
    "table-striped", "table-bordered", "table-hover", "table-responsive",
    "d-none", "d-flex", "d-block", "d-inline", "d-grid",
    "justify-content-center", "align-items-center",
    "text-center", "text-start", "text-end",
    "bg-primary", "bg-secondary", "bg-success", "bg-danger",
    "text-primary", "text-secondary", "text-white", "text-dark",
    "mt-0", "mb-0", "ms-0", "me-0", "mx-auto", "p-0",
    "rounded", "shadow", "border", "overflow-hidden",
    "position-relative", "position-absolute", "position-fixed",
    "visually-hidden", "clearfix", "float-start", "float-end",
    
    # Tailwind common patterns (single words that might be NER'd)
    "flex", "grid", "block", "inline", "hidden", "overflow",
    "relative", "absolute", "fixed", "sticky",
    "rounded", "shadow", "border", "outline",
    "truncate", "antialiased", "subpixel-antialiased",
    "transition", "duration", "transform",
    "opacity", "cursor-pointer", "select-none",
    "sr-only", "not-sr-only",
    
    # Foundation
    "callout", "reveal", "orbit", "sticky-container",
    "top-bar", "title-bar", "off-canvas",
    "cell", "grid-x", "grid-y", "grid-container",
}

# ================================================================
# 📋 YouTube / Google / Facebook internals
# ================================================================

_PLATFORM_INTERNALS = {
    # YouTube JS
    "ytplayer", "ytcfg", "ytInitialData", "ytInitialPlayerResponse",
    "kevlar", "polymer", "iron", "paper",
    "yt-uix", "yt-lockup", "yt-simple-endpoint",
    "ytd-app", "ytd-page-manager", "ytd-browse", "ytd-watch",
    "ytd-video-renderer", "ytd-channel-renderer",
    "ytd-shelf-renderer", "ytd-section-list-renderer",
    "ytd-rich-grid-renderer", "ytd-compact-video-renderer",
    "ytd-comment-renderer", "ytd-mini-guide",
    "ytd-topbar-logo-renderer", "ytd-masthead",
    "ytd-searchbox", "ytd-guide-renderer",
    "yt-formatted-string", "yt-icon", "yt-img-shadow",
    "tp-yt-paper-button", "tp-yt-iron-icon",
    "ytp-cued-thumbnail-overlay", "ytp-large-play-button",
    "ytp-chrome-controls", "ytp-progress-bar",
    "ytp-volume-panel", "ytp-time-display",
    "innertube", "browse_ajax", "next_ajax",
    
    # Google misc
    "gstatic", "googlesyndication", "googletagmanager",
    "gtag", "dataLayer", "gtm", "gpt-ad",
    "recaptcha", "grecaptcha",
    
    # Facebook
    "fb-root", "fb-like", "fb-share", "fb-comments",
    "fbclid", "fb-pixel",
    
    # Analytics / Tracking
    "analytics", "tracking", "pixel", "beacon",
    "utm-source", "utm-medium", "utm-campaign",
    "ga-event", "ga-category", "ga-action",
    "hotjar", "hj-", "clarity", "mouseflow",
}

# ================================================================
# 📋 Generic web garbage words
# ================================================================

_WEB_GARBAGE_WORDS = {
    # Common CSS class name words
    "wrapper", "container", "inner", "outer", "main",
    "primary", "secondary", "tertiary",
    "sidebar", "widget", "module",
    "clearfix", "pull-left", "pull-right",
    "responsive", "mobile", "desktop", "tablet",
    "breakpoint", "viewport",
    
    # Navigation
    "navbar", "navmenu", "breadcrumb", "pagination",
    "prev", "next", "toggle", "toggler", "hamburger",
    "dropdown", "submenu", "sub-menu", "megamenu",
    
    # Layout words
    "layout", "template", "wrapper", "overlay", "backdrop",
    "popup", "modal", "lightbox", "offcanvas", "off-canvas",
    "drawer", "panel", "tab", "tabs", "accordion",
    "carousel", "slider", "swiper", "slick",
    
    # Button/Form CSS
    "btn", "btn-primary", "btn-secondary", "btn-submit",
    "cta", "call-to-action",
    "input", "textarea", "select", "checkbox", "radio",
    "placeholder", "tooltip", "popover",
    
    # Cookie/GDPR/Privacy
    "cookie", "cookies", "gdpr", "consent", "privacy",
    "cookie-banner", "cookie-notice", "cookie-consent",
    "cookie-bar", "cookie-popup", "cookie-modal",
    "cookielaw", "cookiebot", "onetrust",
    
    # CMS/Plugin
    "plugin", "shortcode", "gutenberg", "tinymce",
    "ckeditor", "wysiwyg",
    "jetpack", "yoast", "rankmath", "seo-",
    "acf", "custom-field", "metabox",
    "wpcf7", "contact-form", "gravity-form",
    
    # Social sharing
    "share", "social", "facebook", "twitter", "linkedin",
    "pinterest", "whatsapp", "telegram", "email-share",
    "share-button", "social-icon", "social-link",
    
    # Image/Icon CSS
    "icon", "icons", "fa-", "fas-", "fab-", "far-",
    "dashicons", "genericons", "glyphicon",
    "svg", "sprite", "lazy", "lazyload",
    "thumbnail", "featured-image", "hero-image",
    
    # Loader/Spinner
    "loader", "spinner", "loading", "preloader", "skeleton",
    
    # Common plural/variant forms of HTML elements (spaCy NER picks these up)
    "buttons", "inputs", "labels", "headers", "footers", "sections",
    "containers", "wrappers", "widgets", "sidebars", "navbars",
    "modals", "tooltips", "popovers", "dropdowns", "accordions",
    "carousels", "sliders", "tabs", "panels", "overlays",
    "icons", "badges", "alerts", "toasts",
    
    # User/Account/Auth UI elements
    "account", "login", "logout", "signup", "signin", "signout",
    "register", "forgot-password", "reset-password",
    "username", "password", "email", "avatar", "profile",
    "auth", "oauth", "sso", "mfa",
    
    # Misc web noise
    "nonce", "csrf", "token", "captcha",
    "sitemap", "robots", "canonical",
    "schema", "microdata", "jsonld", "structured-data",
    "amp", "pwa", "manifest",
    "serviceworker", "workbox", "sw-precache",
    "polyfill", "shim", "fallback",
    "webpack", "babel", "eslint", "prettier",
    "minified", "uglified", "sourcemap",
    "debug", "verbose", "production", "development",
    
    # Config/Flag patterns
    "config", "settings", "options", "preferences",
    "enabled", "disabled", "flag", "toggle",
    "killswitch", "experiment", "variant",
    "canary", "beta", "alpha", "nightly",
}


# ================================================================
# 🔧 BUILD COMBINED SET
# ================================================================

def _build_blacklist() -> Set[str]:
    """Buduje połączony set wszystkich garbage words (lowercase)."""
    combined = set()
    
    # Dodaj wszystkie kategorie
    for source in [
        _CSS_PROPERTIES, _CSS_VALUES, _CSS_PSEUDO, _CSS_FUNCTIONS, _CSS_UNITS,
        _HTML_TAGS, _HTML_ATTRIBUTES,
        _JS_KEYWORDS,
        _WORDPRESS_PATTERNS, _CSS_FRAMEWORKS, _PLATFORM_INTERNALS,
        _WEB_GARBAGE_WORDS,
    ]:
        for item in source:
            combined.add(item.lower())
            # Dodaj wersję z myślnikami zamienionymi na spacje
            if '-' in item:
                combined.add(item.replace('-', ' ').lower())
                # Dodaj też poszczególne segmenty
                for part in item.split('-'):
                    if len(part) >= 3:
                        combined.add(part.lower())
            # Wersja z podkreślnikami
            if '_' in item:
                combined.add(item.replace('_', ' ').lower())
                for part in item.split('_'):
                    if len(part) >= 3:
                        combined.add(part.lower())
    
    return combined


# Zbudowany raz przy imporcie
CSS_ENTITY_BLACKLIST = _build_blacklist()

# ================================================================
# 📐 REGEX PATTERNS — szybsze od lookup w secie
# ================================================================

_GARBAGE_REGEX = re.compile(
    r'(?i)'
    r'(?:'
    # CSS vendor prefixes
    r'-?(?:webkit|moz|ms|o)-\w+'
    r'|'
    # CSS variables
    r'var\s*\(|calc\s*\(|rgb[a]?\s*\(|hsl[a]?\s*\('
    r'|'
    # CSS units attached to numbers
    r'\d+(?:px|em|rem|vh|vw|pt|pc|cm|mm|deg|rad|ms|fr|%)'
    r'|'
    # CSS selectors
    r'[.#]\w+[-_]\w+'
    r'|'
    # CSS property:value
    r'\w+\s*:\s*\w+\s*;'
    r'|'
    # HTML entities
    r'&(?:amp|lt|gt|nbsp|quot|#\d+|#x[\da-f]+);'
    r'|'
    # Data attributes
    r'data-[\w-]+'
    r'|'
    # Aria attributes
    r'aria-[\w-]+'
    r'|'
    # WordPress/theme patterns
    r'(?:ast|wp|et[_-]pb|elementor|yoast|wpcf7)[-_]\w+'
    r'|'
    # YouTube internals
    r'(?:ytd|ytp|yt-|kevlar|innertube)[-_]?\w*'
    r'|'
    # BEM-style class names
    r'\w+(?:__\w+|--\w+)'
    r'|'
    # JSON-like patterns
    r'["\{]\w+[":]'
    r'|'
    # Minified code patterns
    r'(?:[a-z]\.[a-z]\.){2,}'
    r'|'
    # File paths
    r'(?:/\w+){2,}'
    r'|'
    # URLs
    r'https?://\S+'
    r'|'
    # Hex colors
    r'#[0-9a-f]{3,8}\b'
    r'|'
    # Common code artifacts
    r'(?:true|false|null|undefined|NaN)\s*[,;\}\]]'
    r')'
)


# ================================================================
# 🎯 MAIN API — is_entity_garbage()
# ================================================================

def is_entity_garbage(text: str) -> bool:
    """
    Sprawdza czy tekst encji to CSS/JS/HTML garbage.
    
    Wielopoziomowa filtracja:
    1. Exact match w blackliście (O(1) lookup)
    2. Regex pattern matching
    3. Heurystyki (proporcja specjalnych znaków, długość)
    4. Segment matching (semicolon, dash, space, dot, underscore)
    5. Numeric-heavy
    6. CamelCase
    7. Font name detection
    8. Encoding artifacts
    
    Returns: True jeśli garbage, False jeśli potencjalnie legit
    """
    if not text or len(text) < 2:
        return True
    
    t = text.strip()
    t_lower = t.lower()
    
    # ---- LEVEL 1: Exact match ----
    if t_lower in CSS_ENTITY_BLACKLIST:
        return True
    
    # ---- LEVEL 2: Regex patterns ----
    if _GARBAGE_REGEX.search(t):
        return True
    
    # ---- LEVEL 3: Special character heuristics ----
    special_chars = set('{}();:[]<>=#.@_-+*~^$|\\/,\'"!?`')
    special_count = sum(1 for c in t if c in special_chars)
    
    if len(t) > 0:
        special_ratio = special_count / len(t)
        # v2.1: Lower threshold for short entities (< 20 chars)
        threshold = 0.08 if len(t) < 20 else 0.12
        if special_ratio > threshold:
            return True
    
    # ---- LEVEL 4: Segment matching ----
    # v2.1: Split on semicolons too — catches "inherit;color", "display;block"
    # v2.2: Split on curly braces — catches "section{display", "div{margin"
    segments = re.split(r'[-_.;\s{}()\[\]]', t_lower)
    segments = [s for s in segments if s]
    
    if segments:
        garbage_segments = sum(1 for s in segments if s in CSS_ENTITY_BLACKLIST)
        # v2.1: If ANY segment is a CSS property/value, flag the whole thing
        if garbage_segments >= 1 and len(segments) <= 3:
            return True
        if len(segments) > 3 and garbage_segments / len(segments) >= 0.4:
            return True
    
    # ---- LEVEL 5: Numeric-heavy ----
    digit_count = sum(1 for c in t if c.isdigit())
    alpha_count = sum(1 for c in t if c.isalpha())
    
    if alpha_count == 0:
        return True
    
    if alpha_count > 0 and digit_count / (alpha_count + digit_count) > 0.5:
        return True
    
    # ---- LEVEL 6: CamelCase code patterns ----
    camel_count = sum(1 for i in range(1, len(t)) if t[i].isupper() and t[i-1].islower())
    if camel_count >= 2:
        return True
    
    # ---- LEVEL 7: Font names ----
    # v2.1: Common font names that spaCy NER picks up as entities
    _FONT_NAMES = {
        "menlo", "monaco", "consolas", "courier", "courier new", "lucida console",
        "lucida sans", "arial", "helvetica", "verdana", "georgia", "palatino",
        "garamond", "bookman", "tahoma", "trebuchet", "impact", "comic sans",
        "times new roman", "segoe ui", "roboto", "open sans", "lato", "montserrat",
        "source sans", "source code", "fira code", "fira sans", "noto sans",
        "ubuntu", "droid sans", "liberation", "dejavu", "bitstream",
        "font awesome", "material icons", "ionicons", "dashicons", "glyphicons",
        "sf pro", "sf mono", "system-ui", "ui-sans-serif", "ui-serif", "ui-monospace",
    }
    if t_lower in _FONT_NAMES:
        return True
    # Check if text is a font stack fragment: "Menlo, Monaco" or "Arial sans-serif"
    if any(font in t_lower for font in _FONT_NAMES if len(font) > 4):
        return True
    
    # ---- LEVEL 8: Encoding artifacts ----
    # v2.1: Mojibake / broken encoding: "krÃ³tkich", "wÅ‚aÅ›ciwy", "zdjÄ™cie"
    if re.search(r'[ÃÅ][^\s]{0,3}[ÃÅ]|Ã[³±¼]|Å[›‚ˆ¼]|Ä[™‡]', t):
        return True
    
    # ---- LEVEL 9: Hex color codes ----
    # v2.1: Standalone hex fragments "A7FF", "FEFC", "FF00"
    if re.match(r'^[A-Fa-f0-9]{3,8}$', t):
        return True
    
    # ---- LEVEL 10: Truncated sentences ----
    # v2.1: Text starting with lowercase + comma = fragment: "unkiem, że opiera się..."
    if re.match(r'^[a-ząćęłńóśźż]{2,8},\s', t):
        return True
    
    return False


# ================================================================
# 📊 STATS
# ================================================================

def get_blacklist_stats() -> dict:
    """Zwraca statystyki blacklisty."""
    return {
        "total_blacklist_entries": len(CSS_ENTITY_BLACKLIST),
        "categories": {
            "css_properties": len(_CSS_PROPERTIES),
            "css_values": len(_CSS_VALUES),
            "css_pseudo": len(_CSS_PSEUDO),
            "css_functions": len(_CSS_FUNCTIONS),
            "css_units": len(_CSS_UNITS),
            "html_tags": len(_HTML_TAGS),
            "html_attributes": len(_HTML_ATTRIBUTES),
            "js_keywords": len(_JS_KEYWORDS),
            "wordpress_patterns": len(_WORDPRESS_PATTERNS),
            "css_frameworks": len(_CSS_FRAMEWORKS),
            "platform_internals": len(_PLATFORM_INTERNALS),
            "web_garbage": len(_WEB_GARBAGE_WORDS),
        }
    }
