import mdx from "@astrojs/mdx";
import { defineConfig } from "astro/config";

export default defineConfig({
  site: "https://www.themarketingstudent.com",
  output: "static",
  trailingSlash: "always",
  integrations: [mdx()],
});
