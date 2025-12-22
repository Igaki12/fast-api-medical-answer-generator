import { extendTheme } from "@chakra-ui/react";

const theme = extendTheme({
  fonts: {
    heading: '"Cinzel", serif',
    body: '"Source Sans 3", sans-serif'
  },
  colors: {
    brand: {
      bg: "#F7F4EE",
      gold: "#C9A14A",
      goldDeep: "#8C6A1F",
      ink: "#1E1B16",
      muted: "#6D5F4B"
    }
  },
  styles: {
    global: {
      body: {
        bg: "brand.bg",
        color: "brand.ink"
      }
    }
  }
});

export default theme;
