import { PeopleWorkspacePage } from './PeopleWorkspacePage'
import { PropertyGalleryMount } from './PropertyGalleryMount'
import { PropertyWorkspacePage } from './PropertyWorkspacePage'

type Props = { permissions: string[]; initialTab?: 'properties' | 'people' }

export function PropertiesPage({ permissions, initialTab = 'properties' }: Props) {
  return initialTab === 'people'
    ? <PeopleWorkspacePage permissions={permissions} />
    : <><PropertyWorkspacePage permissions={permissions} /><PropertyGalleryMount permissions={permissions} /></>
}
