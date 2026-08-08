import assert from "node:assert/strict";
import { cp, mkdir, rm, writeFile } from "node:fs/promises";
import { pathToFileURL } from "node:url";
import path from "node:path";

const [visualizerArgument, outputArgument] = process.argv.slice(2);
assert.ok(visualizerArgument, "usage: render-static.mjs VISUALIZER_ROOT OUTPUT_ROOT");
assert.ok(outputArgument, "usage: render-static.mjs VISUALIZER_ROOT OUTPUT_ROOT");

const visualizerRoot = path.resolve(visualizerArgument);
const outputRoot = path.resolve(outputArgument);
const serverEntry = path.join(visualizerRoot, "dist", "server", "index.js");
const clientRoot = path.join(visualizerRoot, "dist", "client");
const pagesPath = "/partizan-reproducibility/";
const pagesUrl = `https://devinnicholson.github.io${pagesPath}`;

const moduleUrl = pathToFileURL(serverEntry);
moduleUrl.searchParams.set("static-export", Date.now().toString());
const { default: worker } = await import(moduleUrl.href);
const response = await worker.fetch(
  new Request("https://devinnicholson.github.io/", {
    headers: { accept: "text/html" },
  }),
  {
    ASSETS: {
      fetch: async () => new Response("Not found", { status: 404 }),
    },
  },
  {
    waitUntil() {},
    passThroughOnException() {},
  },
);

assert.equal(response.status, 200, "the visualizer did not render successfully");
const html = await response.text();
assert.match(
  html,
  /<title>Partizan \| 193 Graph Forms, One Complete Game<\/title>/i,
);
assert.match(html, /21,697 certified graph forms at three exact values\./);
assert.match(html, /\/partizan-reproducibility\/assets\//);
assert.match(
  html,
  /https:\/\/devinnicholson\.github\.io\/partizan-reproducibility\/og-progressive\.png/,
);
assert.doesNotMatch(html, /localhost/);

await rm(outputRoot, { recursive: true, force: true });
await mkdir(outputRoot, { recursive: true });
await cp(clientRoot, outputRoot, { recursive: true });
await writeFile(path.join(outputRoot, "index.html"), html, "utf8");
await writeFile(path.join(outputRoot, ".nojekyll"), "", "utf8");

console.log(`rendered ${pagesUrl}`);
