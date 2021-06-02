import i18n from 'i18next'
import { initReactI18next } from 'react-i18next'

import resources from '../../public/locales/en'

i18n.use(initReactI18next).init({
  resources,
  lng: 'en',
  debug: false,
  interpolation: {
    escapeValue: false
  }
})

export default i18n
