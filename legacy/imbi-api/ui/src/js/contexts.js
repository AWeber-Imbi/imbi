import React from "react"

// Wraps the fetch function to handle authenticated requests
export const FetchContext = React.createContext(() => {})

// Used to trigger a refresh of the settings
export const FetchSettingsContext = React.createContext(() => {})

// Used to invoke the logout function in index.jsx
export const LogoutContext = React.createContext(() => {})

// Expose common settings
export const SettingsContext = React.createContext({})
