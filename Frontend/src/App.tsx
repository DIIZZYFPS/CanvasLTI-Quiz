
import { Toaster } from 'sonner'
import Index from './pages/Index'
import { ThemeProvider } from './components/ui/theme-provider'

function App() {
  return (
    <>
      <ThemeProvider defaultTheme='system' storageKey='vite-ui-theme'>
        <Toaster position="top-center" richColors />
        <Index />
      </ThemeProvider>
    </>
  )
}

export default App
