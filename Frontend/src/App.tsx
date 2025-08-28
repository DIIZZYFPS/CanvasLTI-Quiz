
import api from './api'
import Index from './pages/Index'

function App() {
  

  const awaitResponse = async () => {
    const response = await api.get('/')
    console.log(response.data)
  }
  awaitResponse()

  return (
    <>
      <Index />
    </>
  )
}

export default App
