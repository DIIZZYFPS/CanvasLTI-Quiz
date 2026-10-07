
import { Toaster } from './components/ui/sonner'
import Index from './pages/Index'
import { ThemeProvider } from './components/ui/theme-provider'

function App() {
  return (
    <>
      <ThemeProvider defaultTheme='light' storageKey='vite-ui-theme'>
        <Toaster position="top-center" />
        <Index />
      </ThemeProvider>
    </>
  )
}

export default App
