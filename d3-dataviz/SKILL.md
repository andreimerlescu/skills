---
name: d3-dataviz
description: Use D3.js v7 to show complex data and draw documentation diagrams (charts, trees, networks, heatmaps, boxes-and-arrows flows), with the d3 MCP server for the API reference and d3-svg for static SVG files. Use it whenever you are asked for a chart, graph, plot, diagram or visualization, or touch D3 code.
license: Apache-2.0
compatibility: opencode, Claude Code, Codex and goose in a roc agent container built with the "d3" image feature
metadata:
  d3: "7.9.0"
  mcp: "d3 (iamfiscus/mcp-d3-server via /opt/mcp-d3-server/stdio.mjs)"
---

# D3 for complex data and documentation diagrams

D3 doesn't have chart types. It gives you the pieces: scales turn data into
positions and colors, shapes and layouts compute geometry, and selections
put SVG elements on the page. You decide what to draw. That is what makes it
good for complex data, and it is also why it is easy to write D3 that looks
right but uses an API from 2015. This skill keeps you on D3 v7, keeps the
output in files a reader can actually open, and has you check your work
before you say it's done.

## What you have

| Thing | Where | Use it for |
|---|---|---|
| `read-d3-api` (MCP tool) | d3 server | **The authority.** D3 v7's own reference, one module or page at a time: `d3-scale/band`, `d3-shape/stack`, `d3-hierarchy/treemap`. No page lists them all. Long pages come in parts (`offset`). |
| `search-d3-docs` (MCP tool) | d3 server | A word or API name across the bundled docs, d3indepth guide and gallery (`forceSimulation`, `scaleBand`). Good for finding examples and explanations. |
| `d3-topic` (MCP tool) | d3 server | Every bundled section whose title mentions a topic (`scale`, `axis`, `hierarchy`). |
| `recommend-chart` (MCP tool) | d3 server | A keyword heuristic for a chart type. A second opinion, not a decision (see *Choosing the form*). |
| `generate-d3-chart` (MCP tool) | d3 server | Bar and line HTML templates only. Anything else returns nothing useful. |
| The D3 repository | `/Users/andrei/friends_of/knowledge/repositories/js/d3` (`$D3_REPO` if set) | The same reference as files: `docs/<module>.md` and `docs/<module>/<page>.md`, `docs/api.md` (index of every symbol), `docs/getting-started.md`, `CHANGES.md` (what changed in v6 and v7), `src/` (the exports). Read-only. |
| `d3-svg` (command) | the agent image | Renders a chart module to a static `.svg` with d3 7.9.0 and jsdom, and fails when marks are broken. |
| d3 itself | `/opt/d3-render/node_modules/d3` | `dist/d3.min.js` for an HTML page that must work offline. |

`ai-generate-d3` and `analyze-data` are switched off: upstream wired them to a
placeholder. The server also exposes `d3-docs://`, `d3-search://` and
`d3-topic://` resources. Don't read `d3-docs://d3-org`, `d3-indepth` or
`d3-gallery` whole: each one is hundreds of kilobytes. The tools above search
the same text and cap what they return.

If a tool is missing, the d3 server isn't enabled for this session. Use the
repository files directly with your file tools. They are the same reference.
If `read-d3-api` says there's no clone, the folder isn't mounted. Say so, and
work from `search-d3-docs` and `/opt/d3-render/node_modules/d3/src` meanwhile.

## Rules

1. **D3 v7 only.** Most D3 code you remember, and most of the bundled
   gallery, is v3–v5. Before you use any D3 function you haven't checked in
   this task, look it up with `read-d3-api` (or the matching `docs/*.md`).
   The table at the end translates the old names.
2. **Documentation diagrams are static `.svg` files** made with `d3-svg` and
   committed next to the Markdown that shows them. Markdown viewers (GitHub,
   GitLab, IDE previews, PDF exports) don't run scripts, so an HTML page or
   an inline `<script>` shows nothing there. Make an HTML page only when
   someone asks for interaction.
3. **Chart modules don't import anything.** `d3-svg` passes `d3` in. Don't
   `npm install`, fetch a CDN or read the network inside a chart.
4. **Every SVG gets** a background, a `<title>` (and a `<desc>` that says the
   finding), a font family, explicit colors and a `viewBox`. That is what
   `frame()` below does. Without a background, a diagram on GitHub in dark
   mode is dark ink on a dark page.
5. **When `d3-svg` exits with 2, the chart is wrong.** It found marks without
   geometry or `NaN` in attributes. Fix the cause (usually a field name or a
   date that wasn't parsed). Don't silence it.
6. **Look at what you made** before you call it done (see *Check your work*).
7. **This workspace's rules still apply.** Scratch files (sample data, test
   renders) go in `./tmp`. Remove files by moving them to `./.deleted`, never
   with `rm`. Install nothing on the host.

## Workflow

1. **Find the question.** Write one sentence the picture must answer ("Which
   service grew fastest since June?"). It decides the form, and it becomes the
   `<desc>`.
2. **Look at the data.** Count the rows, list the fields and their types, and
   find the nulls, the outliers and the time zone. With more than a few
   thousand marks, aggregate first (see *Shaping data*).
3. **Choose the form** from the table below. Use `recommend-chart` only as a
   tiebreaker.
4. **Check the API** for every D3 piece you'll use: `read-d3-api` with
   `d3-scale/band`, `d3-shape/stack`, and so on.
5. **Write the module** from the closest pattern below, with `frame()` pasted
   at the top.
6. **Render:** `d3-svg docs/img/foo.mjs --data docs/img/foo.csv -o docs/img/foo.svg`.
   Fix anything it reports.
7. **Check it**, then embed it: `![Requests per month by service](img/foo.svg)`.
   Keep the `.mjs` and its data beside the `.svg`, so the next person can
   regenerate it.

## Using the d3 MCP server well

- **Look up signatures:** `read-d3-api {"page": "d3-hierarchy/stratify"}`.
  When unsure of the page name, `read-d3-api {}` lists them all, and a wrong
  name suggests close ones.
- **Find an example or explanation:** `search-d3-docs {"query": "stackOffsetWiggle"}`.
  Results name their source. `d3-org` is the official site (current);
  `d3-indepth` is a good tutorial, mostly v6+. `d3-gallery` is old
  bl.ocks-style code (`d3.v4.js`, `d3.event`, `.enter().append()`), so take
  ideas from it, not code.
- **Read around a topic:** `d3-topic {"topic": "transition"}`.
- **Context budget:** every tool caps its answer at about 12,000 characters.
  Search for the narrowest term that works (`scaleSymlog`, not `scale`), and
  read only the page you need. Big pages like `d3-zoom` or `d3-time` come in
  parts. Follow the `offset` the tool gives you only when the part you need
  isn't in the first one.
- **Templates:** `generate-d3-chart {"chartType": "line", "dataFormat": "date,value", "features": ["tooltip"]}`
  returns a whole HTML page that loads `d3.v7.min.js` from a CDN. Use it as a
  start for an interactive page, not for documentation.

## Choosing the form

Choose by the question, not by what the data looks like.

| Question | Form | D3 pieces | Reference |
|---|---|---|---|
| How do a few categories compare? | sorted horizontal bars | `scaleBand`, `scaleLinear`, `axisLeft` | `d3-scale/band` |
| How does a total split, over time or by category? | stacked bars (absolute), or `stackOffsetExpand` (shares) | `stack`, `index` | `d3-shape/stack` |
| How do several series change over time? | lines with labels at their ends; small multiples past ~6 series | `scaleUtc`, `line`, `group` | `d3-shape/line`, `d3-scale/time` |
| How are values spread out? | histogram; box plot or strip plot to compare groups | `bin`, `quantile` | `d3-array/bin`, `d3-array/summarize` |
| How do two numbers relate? | scatter plot; density contours past ~2,000 points | `scaleLinear`, `contourDensity` | `d3-contour/density` |
| Where are the hot spots in category × category (or time)? | heatmap with a legend | `scaleBand` × 2, `scaleSequential` | `d3-scale/sequential`, `d3-scale-chromatic` |
| What contains what (folders, modules, budgets)? | tree (structure), treemap or icicle (size), sunburst only when asked | `stratify`, `tree`, `treemap`, `partition` | `d3-hierarchy/*` |
| What connects to what? | network (force), arc diagram, or adjacency matrix past ~80 nodes | `forceSimulation`; `scaleBand` for a matrix | `d3-force/*` |
| How much flows between groups? | chord diagram (D3 has no Sankey; `d3-sankey` isn't installed) | `chord`, `ribbon` | `d3-chord/*` |
| Where is it? | map | `geoPath`, `geoEqualEarth`, `geoAlbersUsa` (GeoJSON; no TopoJSON client is installed) | `d3-geo/*` |
| How does a system work (architecture, request flow)? | boxes and arrows you place on a grid | `linkHorizontal`, a marker | `d3-shape/link` |

Avoid pie charts with more than 3–4 slices, 3D, dual y-axes and rainbow color
scales. Prefer direct labels to legends. Start bars at zero. Lines don't have
to.

## Shaping data

Most chart bugs are data bugs. Shape the data in the module, before any
drawing code, and keep the input tidy: one row per observation.

- **`d3.autoType`** (which `d3-svg` uses for CSV and TSV) guesses types:
  - `2026-06` and `2026-06-01` become **UTC Date objects**, so format them with
    `d3.utcFormat` and use `scaleUtc` (not `timeFormat`/`scaleTime`, which use
    the computer's local time zone);
  - `"07"` becomes `7` (zip codes and IDs lose their zeros);
  - empty cells become `null`.

  When a type matters, use JSON, or convert the field yourself.
- **Dates as keys:** two `Date` objects are never `===`. D3's `group`,
  `index`, `rollup` and the scale domains compare them by value, but `Map`,
  `Set` and `indexOf` don't, so key by `+d.date`.
- **Group and summarize:**
  - `d3.group(data, d => d.k)` gives Map k → rows;
  - `d3.rollup(data, v => d3.sum(v, d => d.n), d => d.k)` gives Map k → number;
  - `d3.flatRollup` gives the same as `[k, value]` arrays;
  - `d3.index(data, d => d.a, d => d.b)` gives a unique row per key pair (it throws on duplicates, which is a useful check);
  - `d3.groupSort(data, v => -d3.sum(v, d => d.n), d => d.k)` gives the keys ordered by their totals.
- **Tidy to wide for stacks:** `d3.stack()` wants one item per x with one
  value per key. Use `d3.index` by x then key, and a `value` accessor (see the
  stacked pattern).
- **Hierarchies:** from parent IDs, use `d3.stratify().id(d => d.id).parentId(d => d.parent)`.
  From paths (`a/b/c.rs`), use `d3.stratify().path(d => d.path)`, which fills
  in the folders. Then call `root.sum(d => d.size)` before you size anything,
  and `root.sort(...)` for a stable order.
- **Distributions:** `d3.bin().value(d => d.ms).thresholds(30)` (`d3.histogram` is
  the deprecated name), `d3.quantile`, `d3.median`, `d3.deviation`.
- **Too much to draw:** more than a few thousand SVG elements makes slow,
  heavy files. Bin, roll up by time (`d3.utcDay.floor`), or draw contours,
  and say in the `<desc>` what you aggregated.
- **Sort deliberately:** bars by value, unless the categories have a natural
  order (time, size buckets, weekdays).

## `d3-svg`

```
d3-svg chart.mjs [-o out.svg] [--data data.csv|tsv|json] [--width 800] [--height 480]
```

The module exports one function that gets `{ d3, document, data, width, height }`
and returns an `<svg>` element, a D3 selection of one, or an SVG string.
`d3.create("svg")` and `d3.select(document.body)` both work. Exit codes:

- `0`: written;
- `2`: written, but there are marks without geometry (a `<rect>` with no width, a `<path>` with no `d`) or `NaN` in attributes;
- `64`: usage;
- `65`: the module returned something that isn't an `<svg>`.

D3 v7 scales return `undefined` for a missing or misspelled field, and
`.attr(name, undefined)` removes the attribute without an error. Exit code 2
is how you find out.

It runs in jsdom, which has no layout engine, and that limits what a module can do:

- **No text measuring.** `getBBox()`, `getComputedTextLength()` and
  `getBoundingClientRect()` don't exist. Estimate text width as
  `characters × font size × 0.6` (0.55 for narrow labels), and leave margins.
- **No time.** Transitions and timers never run here. Draw the final state,
  and settle force layouts with `simulation.stop()` plus `tick(n)`.
- **No external CSS.** Set colors and fonts as attributes on the elements
  (`fill`, `stroke`, `font-family`), not as classes styled elsewhere.
  `currentColor` (which D3 axes use) takes the root's `color` attribute,
  which `frame()` sets.
- **Fonts are the viewer's.** Use a system font stack; there's nothing to embed.

### `frame()`: paste this at the top of every chart module

```js
// A docs-ready <svg>: size, viewBox, accessible name, font, ink color for
// axes (currentColor) and an opaque background, so it reads in dark mode.
function frame(d3, { width, height, title, desc, x = 0, y = 0, background = "#fff" }) {
  const svg = d3.create("svg")
    .attr("width", width).attr("height", height)
    .attr("viewBox", [x, y, width, height])
    .attr("role", "img")
    .attr("font-family", "system-ui, -apple-system, 'Segoe UI', Helvetica, Arial, sans-serif")
    .attr("font-size", 12)
    .attr("color", "#3b3b3b");
  svg.append("title").text(title);
  if (desc) svg.append("desc").text(desc);
  svg.append("rect").attr("x", x).attr("y", y).attr("width", width).attr("height", height).attr("fill", background);
  return svg;
}
```

Pass `x` and `y` when the layout puts content left of or above the origin, as
the tree pattern does.

## Patterns

Each pattern below is a complete module (after `frame()`), rendered and checked
with `d3-svg` on the data it describes. Copy the closest one, rename the
fields, and change the title and desc.

### Stacked bars from tidy rows

`d3-svg stacked.mjs --data requests.csv --width 640 --height 320`, with
`requests.csv` holding rows of `date,service,requests`.

```js
// Stacked bars from tidy rows: date, service, requests.
export default function ({ d3, data, width, height }) {
  const m = { top: 24, right: 90, bottom: 28, left: 44 };
  const keys = d3.groupSort(data, (v) => -d3.sum(v, (d) => d.requests), (d) => d.service); // biggest at the bottom
  const rows = d3.index(data, (d) => +d.date, (d) => d.service);   // date → service → row
  const series = d3.stack().keys(keys)
    .value(([, byKey], key) => byKey.get(key)?.requests ?? 0)(rows);
  const x = d3.scaleBand([...rows.keys()], [m.left, width - m.right]).padding(0.25);
  const y = d3.scaleLinear([0, d3.max(series.at(-1), (d) => d[1])], [height - m.bottom, m.top]).nice();
  const color = d3.scaleOrdinal(keys, d3.schemeTableau10);

  const svg = frame(d3, { width, height, title: "Requests per month by service",
    desc: "Stacked bars by month; api is the largest share every month." });
  svg.append("g").selectAll("g").data(series).join("g").attr("fill", (s) => color(s.key))
    .selectAll("rect").data((s) => s).join("rect")
      .attr("x", (d) => x(d.data[0])).attr("width", x.bandwidth())
      .attr("y", (d) => y(d[1])).attr("height", (d) => y(d[0]) - y(d[1]));
  svg.append("g").attr("transform", `translate(0,${height - m.bottom})`)
    .call(d3.axisBottom(x).tickFormat(d3.utcFormat("%b %Y")).tickSizeOuter(0));
  svg.append("g").attr("transform", `translate(${m.left},0)`)
    .call(d3.axisLeft(y).ticks(5)).call((g) => g.select(".domain").remove());
  const last = series.map((s) => s.at(-1));                       // label each layer at its last bar
  svg.append("g").selectAll("text").data(series).join("text")
    .attr("x", width - m.right + 6).attr("y", (s, i) => y((last[i][0] + last[i][1]) / 2)).attr("dy", "0.35em")
    .attr("fill", (s) => color(s.key)).text((s) => s.key);
  return svg.node();
}
```

For shares instead of totals, add `.offset(d3.stackOffsetExpand)` and set the
y domain to `[0, 1]` with `d3.format(".0%")` ticks. For grouped bars instead,
use a second `scaleBand` inside each x band (`x1 = d3.scaleBand(keys, [0, x.bandwidth()])`).

### Several series over time

Same data, `--width 640 --height 300`.

```js
// Several series over time, labelled at their ends: date, service, requests.
export default function ({ d3, data, width, height }) {
  const m = { top: 20, right: 70, bottom: 28, left: 44 };
  const series = d3.group(data, (d) => d.service);
  const x = d3.scaleUtc(d3.extent(data, (d) => d.date), [m.left, width - m.right]);
  const y = d3.scaleLinear([0, d3.max(data, (d) => d.requests)], [height - m.bottom, m.top]).nice();
  const color = d3.scaleOrdinal([...series.keys()], d3.schemeTableau10);
  const line = d3.line().x((d) => x(d.date)).y((d) => y(d.requests));

  const svg = frame(d3, { width, height, title: "Requests per month by service" });
  svg.append("g").attr("transform", `translate(0,${height - m.bottom})`)
    .call(d3.axisBottom(x).ticks(d3.utcMonth.every(1)).tickFormat(d3.utcFormat("%b")));
  svg.append("g").attr("transform", `translate(${m.left},0)`)
    .call(d3.axisLeft(y).ticks(5))
    .call((g) => g.select(".domain").remove())
    .call((g) => g.selectAll(".tick line").clone().attr("x2", width - m.left - m.right).attr("stroke-opacity", 0.1));
  svg.append("g").attr("fill", "none").attr("stroke-width", 2).attr("stroke-linejoin", "round")
    .selectAll("path").data(series).join("path")
      .attr("stroke", ([k]) => color(k)).attr("d", ([, v]) => line(v));
  svg.append("g").selectAll("text").data(series).join("text")
    .attr("x", ([, v]) => x(v.at(-1).date) + 6).attr("y", ([, v]) => y(v.at(-1).requests)).attr("dy", "0.35em")
    .attr("fill", ([k]) => color(k)).text(([k]) => k);
  return svg.node();
}
```

Past about six series, draw one small chart per series with a shared y scale
(small multiples), or highlight the one that matters and grey the rest.

### Distribution

Rows with `ms`, `--width 640 --height 280`.

```js
// Distribution of one number: rows with `ms`.
export default function ({ d3, data, width, height }) {
  const m = { top: 20, right: 20, bottom: 36, left: 44 };
  const bins = d3.bin().value((d) => d.ms).thresholds(30)(data);
  const x = d3.scaleLinear([bins[0].x0, bins.at(-1).x1], [m.left, width - m.right]);
  const y = d3.scaleLinear([0, d3.max(bins, (b) => b.length)], [height - m.bottom, m.top]).nice();
  const p95 = d3.quantile(data, 0.95, (d) => d.ms);

  const svg = frame(d3, { width, height, title: "Response times", desc: `${data.length} requests; 95th percentile ${Math.round(p95)} ms` });
  svg.append("g").attr("fill", "#4e79a7").selectAll("rect").data(bins).join("rect")
    .attr("x", (b) => x(b.x0) + 0.5).attr("width", (b) => Math.max(0, x(b.x1) - x(b.x0) - 1))
    .attr("y", (b) => y(b.length)).attr("height", (b) => y(0) - y(b.length));
  svg.append("line").attr("x1", x(p95)).attr("x2", x(p95)).attr("y1", m.top).attr("y2", height - m.bottom)
    .attr("stroke", "#e15759").attr("stroke-dasharray", "4 3");
  svg.append("text").attr("x", x(p95) + 4).attr("y", m.top + 10).attr("fill", "#e15759").text(`p95 ${Math.round(p95)} ms`);
  svg.append("g").attr("transform", `translate(0,${height - m.bottom})`).call(d3.axisBottom(x).ticks(width / 80))
    .call((g) => g.append("text").attr("x", width - m.right).attr("y", 32).attr("fill", "currentColor")
      .attr("text-anchor", "end").text("response time (ms) →"));
  svg.append("g").attr("transform", `translate(${m.left},0)`).call(d3.axisLeft(y).ticks(5));
  return svg.node();
}
```

Data with a long tail: mark a percentile (as here), cap the axis and say so,
or bin on a log scale (`d3.scaleLog` with `thresholds` from `x.ticks()`).

### Heatmap with a legend

Rows of `day,hour,n`, `--width 720 --height 260`.

```js
// Two categories and a value: rows with day ("Mon"…), hour (0-23), n.
export default function ({ d3, data, width, height }) {
  const m = { top: 16, right: 16, bottom: 52, left: 40 };
  const days = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
  const x = d3.scaleBand(d3.range(24), [m.left, width - m.right]).padding(0.06);
  const y = d3.scaleBand(days, [m.top, height - m.bottom]).padding(0.06);
  const max = d3.max(data, (d) => d.n);
  const color = d3.scaleSequential([0, max], d3.interpolateBlues);

  const svg = frame(d3, { width, height, title: "Sessions by weekday and hour" });
  svg.append("g").selectAll("rect").data(data).join("rect")
    .attr("x", (d) => x(d.hour)).attr("y", (d) => y(d.day))
    .attr("width", x.bandwidth()).attr("height", y.bandwidth()).attr("fill", (d) => color(d.n))
    .append("title").text((d) => `${d.day} ${d.hour}:00 — ${d.n}`);   // hover text in browsers
  svg.append("g").attr("transform", `translate(0,${height - m.bottom})`)
    .call(d3.axisBottom(x).tickValues(d3.range(0, 24, 3)).tickFormat((h) => `${h}:00`).tickSize(0))
    .call((g) => g.select(".domain").remove());
  svg.append("g").attr("transform", `translate(${m.left},0)`)
    .call(d3.axisLeft(y).tickSize(0)).call((g) => g.select(".domain").remove());
  // Legend: a gradient bar with its own axis. Every color scale needs one.
  const lw = 160, lx = width - m.right - lw, ly = height - 18;
  const grad = svg.append("defs").append("linearGradient").attr("id", "ramp");
  grad.selectAll("stop").data(d3.ticks(0, 1, 10)).join("stop")
    .attr("offset", (t) => t).attr("stop-color", (t) => color(t * max));
  svg.append("rect").attr("x", lx).attr("y", ly - 10).attr("width", lw).attr("height", 8).attr("fill", "url(#ramp)");
  svg.append("g").attr("transform", `translate(0,${ly - 2})`)
    .call(d3.axisBottom(d3.scaleLinear([0, max], [lx, lx + lw])).ticks(4).tickSize(3))
    .call((g) => g.select(".domain").remove());
  return svg.node();
}
```

Use sequential schemes (`interpolateBlues`, `interpolateViridis`) for amounts.
Use diverging ones (`scaleDiverging([min, 0, max], d3.interpolateRdBu)`) only
when the middle means something, such as zero change.

### File or module tree (documentation)

A CSV with one `path` column, `--width 640`. The height follows the tree.

```js
// A file or module tree from paths. data: rows with a `path` column
// ("src/mcp/catalog.rs"), CSV or JSON. Folders are filled in from the paths.
export default function ({ d3, data, width }) {
  const root = d3.stratify().path((d) => d.path)(data);
  root.sort((a, b) => d3.descending(!!a.children, !!b.children) || d3.ascending(a.id, b.id)); // folders first
  const name = (d) => d.id.split("/").pop() || "/";
  const charW = 7;                               // ≈ width of one 12px character (no text measuring)
  const left = name(root).length * charW + 14;   // room for the root's label, drawn to its left
  const right = d3.max(root.leaves(), (d) => name(d).length) * charW + 14;
  const dx = 20;                                 // vertical gap between rows
  const dy = (width - left - right) / (root.height || 1); // horizontal gap between levels
  d3.tree().nodeSize([dx, dy])(root);
  const [x0, x1] = d3.extent(root.descendants(), (d) => d.x);
  const height = x1 - x0 + dx * 2;

  const svg = frame(d3, { width, height, x: -left, y: x0 - dx,
    title: "Repository layout", desc: `${root.leaves().length} files in ${root.descendants().length - root.leaves().length} folders` });
  svg.append("g").attr("fill", "none").attr("stroke", "#b0b0b0").attr("stroke-width", 1.2)
    .selectAll("path").data(root.links()).join("path")
      .attr("d", d3.linkHorizontal().x((d) => d.y).y((d) => d.x));
  const node = svg.append("g").selectAll("g").data(root.descendants()).join("g")
    .attr("transform", (d) => `translate(${d.y},${d.x})`);
  node.append("circle").attr("r", 3.5).attr("fill", (d) => (d.children ? "#3b3b3b" : "#9a9a9a"));
  node.append("text")
    .attr("dy", "0.32em").attr("x", (d) => (d.children ? -7 : 7))
    .attr("text-anchor", (d) => (d.children ? "end" : "start"))
    .attr("fill", "#3b3b3b")
    .attr("paint-order", "stroke").attr("stroke", "#fff").attr("stroke-width", 3)
    .text(name);
  return svg.node();
}
```

For sizes rather than structure, use the same `stratify` with `root.sum(d => d.size)`
and `d3.treemap().size([width, height]).paddingInner(2).paddingTop(18)(root)`,
then draw `rect`s from `x0`, `y0`, `x1` and `y1`. Read `d3-hierarchy/treemap`
first.

### Boxes and arrows (architecture and flow diagrams)

JSON `{nodes, edges}` with grid positions. Width and height follow the grid.

```js
// Boxes and arrows on a grid, for small architecture or flow diagrams
// (up to ~15 boxes). You place the boxes (col, row); D3 draws them.
// data: { nodes: [{ id, label, col, row, kind? }], edges: [{ from, to, label? }] }
export default function ({ d3, data }) {
  const colW = 230, rowH = 70, boxH = 34, pad = 24, font = 12;
  const boxW = (d) => Math.max(90, d.label.length * font * 0.6 + 24); // no text measuring in d3-svg
  const cols = d3.max(data.nodes, (d) => d.col) + 1;
  const rows = d3.max(data.nodes, (d) => d.row) + 1;
  const width = pad * 2 + (cols - 1) * colW + (colW - 40);
  const height = pad * 2 + (rows - 1) * rowH + boxH;
  const byId = new Map(data.nodes.map((d) => [d.id, d]));
  const cx = (d) => pad + d.col * colW + (colW - 40) / 2;
  const cy = (d) => pad + d.row * rowH + boxH / 2;
  const fill = d3.scaleOrdinal(["host", "container", "remote"], ["#e8f0fb", "#eaf6ec", "#fbefe3"]).unknown("#f1f1f1");

  const svg = frame(d3, { width, height, title: "Request flow", desc: data.nodes.map((d) => d.label).join(", ") });
  svg.append("defs").append("marker")
      .attr("id", "arrow").attr("viewBox", "0 0 10 10").attr("refX", 9).attr("refY", 5)
      .attr("markerWidth", 7).attr("markerHeight", 7).attr("orient", "auto-start-reverse")
    .append("path").attr("d", "M0,0L10,5L0,10z").attr("fill", "#6b6b6b");

  const link = d3.linkHorizontal();
  svg.append("g").attr("fill", "none").attr("stroke", "#6b6b6b").attr("stroke-width", 1.4)
    .selectAll("path").data(data.edges).join("path")
      .attr("marker-end", "url(#arrow)")
      .attr("d", (e) => {
        const a = byId.get(e.from), b = byId.get(e.to);
        return link({ source: [cx(a) + boxW(a) / 2, cy(a)], target: [cx(b) - boxW(b) / 2 - 2, cy(b)] });
      });
  // Edge labels sit just above the arrowhead, where every link runs level.
  svg.append("g").attr("font-size", 11).attr("fill", "#555").attr("text-anchor", "end")
    .selectAll("text").data(data.edges.filter((e) => e.label)).join("text")
      .attr("x", (e) => cx(byId.get(e.to)) - boxW(byId.get(e.to)) / 2 - 10)
      .attr("y", (e) => cy(byId.get(e.to)) - 7)
      .text((e) => e.label);

  const box = svg.append("g").selectAll("g").data(data.nodes).join("g")
    .attr("transform", (d) => `translate(${cx(d) - boxW(d) / 2},${cy(d) - boxH / 2})`);
  box.append("rect").attr("width", boxW).attr("height", boxH).attr("rx", 6)
    .attr("fill", (d) => fill(d.kind)).attr("stroke", "#8a8a8a");
  box.append("text").attr("x", (d) => boxW(d) / 2).attr("y", boxH / 2).attr("dy", "0.35em")
    .attr("text-anchor", "middle").attr("font-size", font).attr("fill", "#222").text((d) => d.label);
  return svg.node();
}
```

D3 has no automatic layout for flowcharts. Placing boxes on a grid yourself is
the honest way to draw one, and it keeps the picture stable when someone edits
it later. Keep to one direction (left to right), at most about 15 boxes, and
color by one property (where it runs, who owns it) explained in the text. For
a strict hierarchy, use the tree pattern. For many cross-links, use the
network pattern.

### Network

JSON `{nodes: [{id, group}], links: [{source, target}]}`, `--width 640 --height 360`.

```js
// A network laid out by force, settled before drawing (no animation in a file).
// data: { nodes: [{ id, group? }], links: [{ source, target }] }
export default function ({ d3, data, width, height }) {
  const nodes = data.nodes.map((d) => ({ ...d }));   // the simulation mutates its inputs
  const links = data.links.map((d) => ({ ...d }));
  const sim = d3.forceSimulation(nodes)
    .force("link", d3.forceLink(links).id((d) => d.id).distance(70))
    .force("charge", d3.forceManyBody().strength(-260))
    .force("collide", d3.forceCollide(28))
    .force("x", d3.forceX(width / 2).strength(0.05))
    .force("y", d3.forceY(height / 2).strength(0.08))
    .stop();
  sim.tick(Math.ceil(Math.log(sim.alphaMin()) / Math.log(1 - sim.alphaDecay()))); // ≈300 ticks
  for (const n of nodes) {                              // keep everything inside the frame
    n.x = Math.max(40, Math.min(width - 40, n.x));
    n.y = Math.max(20, Math.min(height - 20, n.y));
  }
  const color = d3.scaleOrdinal(d3.schemeTableau10);

  const svg = frame(d3, { width, height, title: "Service dependencies" });
  svg.append("g").attr("stroke", "#a0a0a0").attr("stroke-width", 1.2)
    .selectAll("line").data(links).join("line")
      .attr("x1", (d) => d.source.x).attr("y1", (d) => d.source.y)
      .attr("x2", (d) => d.target.x).attr("y2", (d) => d.target.y);
  const node = svg.append("g").selectAll("g").data(nodes).join("g")
    .attr("transform", (d) => `translate(${d.x},${d.y})`);
  node.append("circle").attr("r", 7).attr("fill", (d) => color(d.group ?? 0)).attr("stroke", "#fff").attr("stroke-width", 1.5);
  node.append("text").attr("y", -11).attr("text-anchor", "middle").attr("fill", "#3b3b3b")
    .attr("paint-order", "stroke").attr("stroke", "#fff").attr("stroke-width", 3).text((d) => d.id);
  return svg.node();
}
```

Past about 80 nodes, a force layout becomes a hairball. Use an adjacency
matrix (two `scaleBand`s, like the heatmap) or group the nodes first.

## Color and accessibility

- **Categories:** `d3.schemeTableau10` (up to 10). Past that, group the small
  ones into "other". Keep the same category in the same color across every
  figure in a document by building the scale from the full, sorted list of
  keys.
- **Amounts:** use sequential scales (`interpolateBlues`, `interpolateViridis`,
  `interpolateCividis`). For signed change, use diverging scales
  (`interpolateRdBu`, `interpolatePuOr`). Don't use `interpolateRainbow` or
  `interpolateSinebow` for data.
- **Never encode with color alone.** Add a direct label, a position or a
  pattern. Check that text has at least 4.5:1 contrast on the background.
- `role="img"`, `<title>` and `<desc>` (from `frame()`) are what screen
  readers and search see. Write the desc as the finding ("api grew 42% since
  June"), not as "a bar chart".
- Use the same alt text in the Markdown: `![api grew 42% since June](img/requests.svg)`.

## Interactive pages (only when asked)

Write a standalone HTML file with the D3 version pinned:

```html
<!doctype html>
<meta charset="utf-8">
<title>Requests by service</title>
<div id="chart"></div>
<script type="module">
  import * as d3 from "https://cdn.jsdelivr.net/npm/d3@7.9.0/+esm";
  // or, offline: copy /opt/d3-render/node_modules/d3/dist/d3.min.js beside the
  // page and load it with a classic <script src="d3.min.js"> (global d3).
  const data = await d3.csv("requests.csv", d3.autoType);
  // …the same module code, then:
  // document.getElementById("chart").append(svg.node());
</script>
```

- **Events:** listeners get `(event, d)`. Use `d3.pointer(event, svg.node())`
  for coordinates. There's no `d3.event` and no `d3.mouse`.
- **Tooltips:** a positioned `<div>`, or the `<title>` child of each mark (free,
  and accessible).
- **Zoom and pan:** `d3.zoom().scaleExtent([1, 8]).on("zoom", ({transform}) => g.attr("transform", transform))`.
  For axes, use `transform.rescaleX(x)`. Read `d3-zoom` first.
- **Motion:** `selection.transition().duration(300)`, skipped when
  `matchMedia("(prefers-reduced-motion: reduce)").matches`.
- **Many points:** past roughly 5,000 marks, draw to `<canvas>` with
  `d3.line().context(ctx)` or `d3.geoPath(projection, ctx)`, and use
  `d3.Delaunay.from(points).find(x, y)` for hover.
- Keep the chart code a function of `(d3, data, width, height)`, like the
  modules here, so the same code also renders a static SVG for the docs.

## Old D3 → D3 v7

| You may remember (v3–v5) | D3 v7 |
|---|---|
| `d3.scale.linear()`, `d3.scale.ordinal()`, `d3.time.scale()` | `d3.scaleLinear()`, `d3.scaleOrdinal()` / `d3.scaleBand()`, `d3.scaleUtc()` / `d3.scaleTime()` |
| `d3.svg.axis().scale(x).orient("bottom")` | `d3.axisBottom(x)` |
| `d3.svg.line()`, `d3.svg.area()`, `d3.svg.arc()` | `d3.line()`, `d3.area()`, `d3.arc()` |
| `.interpolate("monotone")` | `.curve(d3.curveMonotoneX)` |
| `d3.layout.force()`, `.tree()`, `.pack()`, `.stack()`, `.histogram()` | `d3.forceSimulation()`, `d3.tree()`, `d3.pack()`, `d3.stack()`, `d3.bin()` |
| `d3.nest().key(...).rollup(...)` | `d3.group()`, `d3.rollup()`, `d3.flatRollup()`, `d3.index()` |
| `d3.csv(url, (err, data) => …)` | `const data = await d3.csv(url, d3.autoType)` |
| `selection.on("click", function (d) { d3.event … })` | `selection.on("click", (event, d) => …)` |
| `d3.mouse(this)` | `d3.pointer(event, this)` |
| `.data(d).enter().append("rect")` + `.exit().remove()` + `.merge()` | `.data(d).join("rect")` (or `join(enter => …, update => …, exit => …)`) |
| `d3.values(obj)`, `d3.keys(obj)`, `d3.map()`, `d3.set()` | `Object.values`, `Object.keys`, `Map`, `Set` (or `d3.InternMap`) |
| `d3.schemeCategory20` | gone: `d3.schemeTableau10`, or group categories |
| `d3.timeFormat` on dates parsed by `autoType` | `d3.utcFormat` (autoType dates are UTC) |

`CHANGES.md` in the D3 repository lists every change from v5 to v6 and v6 to
v7, when you meet something not listed here.

## Check your work

Before you report a chart as done:

1. `d3-svg` exited 0. You fixed any warning; you didn't silence it.
2. **Look at it.** Use whatever your session has:
   - `chrome-devtools` (or `playwright`) MCP: open the `.svg` with a `file://`
     URL. roc mounts your working folder at the same path on the host, so the
     host browser can open it. Take a screenshot and read it.
   - Otherwise, inspect the numbers. Take the extents of the drawn
     coordinates (`grep -o 'x="[^"]*"' foo.svg | sort -u | head`) and confirm
     nothing sits outside the `viewBox`.
3. The data is right. Pick two or three marks and check their values against
   the source by hand (a bar's height against its row; a total against
   `d3.sum`).
4. The picture answers the question you wrote in step 1, and the `<desc>`
   says the answer.
5. Labels don't collide or get cut off at the edges. The axes have units. A
   color scale has a legend or direct labels.
6. It reads on both a white and a dark page (the frame has a background).
7. The `.mjs`, its data and the `.svg` sit together, and the Markdown links
   the `.svg` with real alt text.

Then report the file paths and the one-sentence finding, plus anything you
aggregated, dropped or assumed about the data.
