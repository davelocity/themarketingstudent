import { slug as githubSlug } from "github-slugger";

function textOf(node) {
  if (node.type === "text") return node.value ?? "";
  if (!Array.isArray(node.children)) return "";
  return node.children.map(textOf).join("");
}

function walk(node) {
  if (node.type === "element" && /^h[1-6]$/.test(node.tagName)) {
    const generated = githubSlug(textOf(node));
    const current = node.properties?.id;
    if (current && generated && current !== generated) {
      node.children.unshift({
        type: "element",
        tagName: "span",
        properties: { id: generated, hidden: true },
        children: [],
      });
    }
  }

  if (Array.isArray(node.children)) {
    for (const child of node.children) walk(child);
  }
}

/** Keep github-slugger ids as aliases when a heading uses a custom Ghost id. */
export function rehypeAliasHeadingIds() {
  return (tree) => walk(tree);
}
