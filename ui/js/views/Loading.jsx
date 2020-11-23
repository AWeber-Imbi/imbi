import React from 'react'
import { useTranslation } from 'react-i18next'

export default () => {
    const { t } = useTranslation()
    return (
        <>
            <header>
                <nav className="navbar navbar-inverse navbar-expand-lg bg-primary fixed-top loading">
                    <a className="navbar-brand text-white h1 mb-0" href="/">
                        <span className="fab fa-earlybirds"></span>
                        {t('common.brandName')}
                    </a>
                </nav>
            </header>
            <div className="main">
                <div className="loading">
                    <h1>
                        <span className="fas fa-spinner fa-spin"></span>
                        {t('common.loading')}
                    </h1>
                </div>
            </div>
        </>
    )
}
