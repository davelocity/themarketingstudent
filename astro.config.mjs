import mdx from "@astrojs/mdx";
import { defineConfig } from "astro/config";
import rehypeSlug from "rehype-slug";
import remarkCustomHeaderId from "remark-custom-header-id";
import { rehypeAliasHeadingIds } from "./src/lib/rehype-alias-heading-ids.js";

export default defineConfig({
  site: "https://www.themarketingstudent.com",
  output: "static",
  trailingSlash: "always",
  integrations: [mdx()],
  markdown: {
    remarkPlugins: [remarkCustomHeaderId],
    rehypePlugins: [rehypeSlug, rehypeAliasHeadingIds],
  },
});
