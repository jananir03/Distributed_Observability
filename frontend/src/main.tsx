import React from 'react'
import ReactDOM from 'react-dom/client'
import { CssBaseline, ThemeProvider, createTheme } from '@mui/material'
import App from './App'
import './styles/global.css'

const theme = createTheme({
  palette: {
    mode: 'light',
    primary: { main: '#5b5bd6', light: '#efefff', dark: '#4141a9' },
    secondary: { main: '#17a89b' },
    background: { default: '#f5f7fb', paper: '#ffffff' },
    text: { primary: '#182230', secondary: '#667085' },
    success: { main: '#158f72' },
    warning: { main: '#c77a19' },
    error: { main: '#d44955' },
    divider: '#e8ecf3',
  },
  shape: { borderRadius: 14 },
  typography: {
    fontFamily: '"Inter", "Segoe UI", Roboto, Helvetica, Arial, sans-serif',
    h4: { fontWeight: 750, letterSpacing: '-0.04em' },
    h5: { fontWeight: 720, letterSpacing: '-0.03em' },
    h6: { fontWeight: 700, letterSpacing: '-0.02em' },
    button: { textTransform: 'none', fontWeight: 650 },
  },
  components: {
    MuiCard: { styleOverrides: { root: { border: '1px solid #e8ecf3', boxShadow: '0 8px 24px rgba(23, 35, 79, 0.035)' } } },
    MuiButton: { defaultProps: { disableElevation: true } },
    MuiTableCell: { styleOverrides: { root: { borderColor: '#edf0f5' } } },
  },
})

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <ThemeProvider theme={theme}>
      <CssBaseline />
      <App />
    </ThemeProvider>
  </React.StrictMode>,
)
