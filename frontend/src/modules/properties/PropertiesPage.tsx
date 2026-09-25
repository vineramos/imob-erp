import { PeopleWorkspacePage } from './PeopleWorkspacePage'
import { PropertyOwnerAutocompleteMount } from './PropertyOwnerAutocompleteMount'
import { PropertyWorkspacePage } from './PropertyWorkspacePage'
import './property-homologation.css'

type Props = { permissions: string[]; initialTab?: 'properties' | 'people' }

export function PropertiesPage({ permissions, initialTab = 'properties' }: Props) {
  return initialTab === 'people'
    ? <PeopleWorkspacePage permissions={permissions} />
    : <><PropertyWorkspacePage permissions={permissions} /><PropertyOwnerAutocompleteMount /></>
}
