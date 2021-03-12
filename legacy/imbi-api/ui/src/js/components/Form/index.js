import { Field } from './Field'
import { ModalForm } from './ModalForm'
import { MultiSectionForm } from './MultiSectionForm'
import { SimpleForm } from './SimpleForm'
import { IconSelect } from './IconSelect'
import { NumericInput } from './NumericInput'
import { Section } from './Section'
import { Select } from './Select'
import { TextArea } from './TextArea'
import { TextInput } from './TextInput'
import { Toggle } from './Toggle'
import { validateObject, validateURLs } from './validate'

export const Form = {
  SimpleForm: SimpleForm,
  ModalForm: ModalForm,
  MultiSectionForm: MultiSectionForm,
  Field: Field,
  IconSelect: IconSelect,
  NumericInput: NumericInput,
  Section: Section,
  Select: Select,
  TextArea: TextArea,
  TextInput: TextInput,
  Toggle: Toggle,
  validateObject: validateObject,
  validateURLs: validateURLs
}
