import { PeopleWorkspacePage } from './PeopleWorkspacePage'
import { PropertyWorkspacePage } from './PropertyWorkspacePage'

type Props = { permissions: string[]; initialTab?: 'properties' | 'people' }

export function PropertiesPage({ permissions, initialTab = 'properties' }: Props) {
  return initialTab === 'people'
    ? <PeopleWorkspacePage permissions={permissions} />
    : <PropertyWorkspacePage permissions={permissions} />
}
