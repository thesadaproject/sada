import "@fontsource-variable/source-sans-3";
import "@fontsource/eb-garamond/400.css";
import "@fontsource/amiri/400.css";
import "../src/preview.css";
import type { Preview } from "@storybook/react-vite";

const preview: Preview = {
  parameters: { layout: "fullscreen", controls: { disableSaveFromUI: true } },
};
export default preview;
