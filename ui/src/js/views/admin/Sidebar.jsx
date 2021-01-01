import PropTypes from "prop-types";
import React, {useState} from "react"
import {Link} from "@reach/router"
import {FontAwesomeIcon} from "@fortawesome/react-fontawesome";
import {faBox, faBuilding, faCloud, faCogs, faCookie, faCubes,
        faExternalLinkAlt, faRuler, faUserFriends, faUsers} from "@fortawesome/free-solid-svg-icons"

const menuClasses = "group w-full flex items-center p-2 text-sm text-gray-600 rounded-md hover:text-blue-700 hover:bg-gray-50"
const menuItemClass = {
  true: menuClasses + " font-bold",
  false: menuClasses
}
function MenuItem({value, to, icon}) {

  return (
    <Link getProps={({isCurrent}) => {return {className: menuItemClass[isCurrent]}}}
          key={to.replace(/\//gi, "_") + "-nav-item"}
          to={to}>
      <div className="inline-block w-6 mr-2 text-center">
        <FontAwesomeIcon icon={icon}/>
      </div>
      {value}
    </Link>
  )
}
MenuItem.propTypes = {
  value: PropTypes.string.isRequired,
  to: PropTypes.string.isRequired,
  icon: PropTypes.object.isRequired
}

const sectionIndicatorClasses = "h-5 w-5 ml transform text-gray-400 group-hover:text-gray-400 transition-colors ease-in-out duration-150  "
function Section({open, name, children, onClick}) {
  return (
    <div className="space-y-1 mt-2">
      <button className="bg-white text-gray-600 hover:text-blue-700 group w-full flex items-center pr-2 pt-2 rounded-md focus:outline-none"
              onClick={() => onClick(name)}>
        <svg className={open === true ? sectionIndicatorClasses + " rotate-90" : sectionIndicatorClasses}
             viewBox="0 0 20 20" aria-hidden="true">
          <path d="M6 6L14 10L6 14V6Z" fill="currentColor"/>
        </svg>
        {name}
      </button>
      <div className={"ml-2 " + (open === true ? "visible" : "hidden")}>
        {children}
      </div>
    </div>
  )
}
Section.propTypes = {
  open: PropTypes.bool.isRequired,
  name: PropTypes.string.isRequired,
  children: PropTypes.node,
  onClick: PropTypes.func.isRequired
}

function Sidebar() {
  const [openSections, setOpenSections] = useState({"Settings": true})

  function onClick(name) {
    setOpenSections({...openSections, [name]: openSections[name] === undefined ? true : !openSections[name]})
  }

  return (
    <nav className="flex-shrink h-full w-64 bg-white overflow-y-auto border-r border-gray-200 py-4 px-2">
      <h1 className="font-gray-600 ml-2 text-lg">Administration</h1>
      <Section name="Settings" open={openSections["Settings"] === true} onClick={onClick}>
        <MenuItem value="Configuration Systems" to="/ui/admin/configuration-systems" icon={faBox}/>
        <MenuItem value="Cookie Cutters" to="/ui/admin/cookie-cutters" icon={faCookie}/>
        <MenuItem value="Data Centers" to="/ui/admin/data-centers" icon={faBuilding}/>
        <MenuItem value="Environments" to="/ui/admin/environments" icon={faCloud}/>
        <MenuItem value="Orchestration Systems" to="/ui/admin/orchestration-systems" icon={faCogs}/>
        <MenuItem value="Project Fact Types" to="/ui/admin/project-fact-types" icon={faRuler}/>
        <MenuItem value="Project Link Types" to="/ui/admin/project-link-types" icon={faExternalLinkAlt}/>
        <MenuItem value="Project Types" to="/ui/admin/project-types" icon={faCubes}/>
      </Section>
      <Section name="User Management"  open={openSections["User Management"] === true} onClick={onClick}>
        <MenuItem value="Users" to="/ui/admin/users" icon={faUserFriends}/>
        <MenuItem value="Groups" to="/ui/admin/groups" icon={faUsers}/>
      </Section>
    </nav>
  )
}

Sidebar.propTypes = {}

export default Sidebar
