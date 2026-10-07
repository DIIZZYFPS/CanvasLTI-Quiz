import { Toaster as Sonner } from "sonner"
import { useTheme } from "./theme-provider"

type ToasterProps = React.ComponentProps<typeof Sonner>

// sonner's Toaster, following the app's own theme (see theme-provider). It used to read the
// theme from `next-themes`, a second theme library the app never wired up, and App rendered
// sonner's Toaster directly - so toasts stayed light-coloured in dark mode.
const Toaster = (props: ToasterProps) => {
  const { theme } = useTheme()

  return <Sonner theme={theme} richColors {...props} />
}

export { Toaster }
