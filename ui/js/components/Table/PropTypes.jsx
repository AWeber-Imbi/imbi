import PropTypes from 'prop-types'

export const Column = {
    changeCallback: PropTypes.func,
    editable: PropTypes.bool,
    editingCallback: PropTypes.func,
    error: PropTypes.bool,
    errorHelp: PropTypes.string,
    formatter: PropTypes.func,
    headerStyle: PropTypes.object,
    isIcon: PropTypes.string,
    keyField: PropTypes.string,
    name: PropTypes.string,
    options: PropTypes.arrayOf(
        PropTypes.shape({
            label: PropTypes.string,
            value: PropTypes.oneOfType([
                PropTypes.bool,
                PropTypes.number,
                PropTypes.string,
            ]),
        })
    ),
    placeholder: PropTypes.string,
    style: PropTypes.object,
    title: PropTypes.string,
    type: PropTypes.oneOf(['text', 'select']),
    updateCallback: PropTypes.func,
    value: PropTypes.oneOfType([
        PropTypes.bool,
        PropTypes.number,
        PropTypes.string,
    ]),
}

export const Columns = PropTypes.arrayOf(PropTypes.shape(Column))
