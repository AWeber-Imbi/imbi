--
-- PostgreSQL database dump
--

-- Dumped from database version 12.5
-- Dumped by pg_dump version 13.1

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

--
-- Data for Name: users; Type: TABLE DATA; Schema: v1; Owner: imbi
--

COPY v1.users (username, created_at, last_seen_at, user_type, external_id, email_address, display_name, password) FROM stdin;
gavinr	2021-02-02 15:01:43.172148-05	2021-02-06 13:17:09.11881-05	ldap	uid=gavinr,cn=users,cn=accounts,dc=aweberint,dc=com	gavinr@aweber.com	Gavin Roy	\N
\.


--
-- Data for Name: authentication_tokens; Type: TABLE DATA; Schema: v1; Owner: postgres
--

COPY v1.authentication_tokens (token, username, name, created_at, expires_at, last_used_at) FROM stdin;
\.


--
-- Data for Name: configuration_systems; Type: TABLE DATA; Schema: v1; Owner: imbi
--

COPY v1.configuration_systems (name, created_at, created_by, last_modified_at, last_modified_by, description, icon_class) FROM stdin;
Consul	2021-01-31 16:17:10.132596-05	test	2021-01-31 16:23:53.870839-05	test	Consul provides DNS-based service discovery and distributed Key-value storage, segmentation and configuration. Registered services and nodes can be queried using a DNS interface or an HTTP interface.	imbi consul
Ansible	2021-01-31 16:25:49.591641-05	test	\N	\N	Ansible is an open-source software provisioning, configuration management, and application-deployment tool enabling infrastructure as code.	imbi ansible
Chef	2021-01-31 16:27:10.4064-05	test	\N	\N	Chef is a configuration management tool written in Ruby and Erlang. It uses a pure-Ruby, domain-specific language for writing system configuration "recipes".	fas sliders-h
Puppet	2021-01-31 16:27:32.257247-05	test	\N	\N	Puppet is a software configuration management tool which includes its own declarative language to describe system configuration.	fas sliders-h
Kubernetes Config Map	2021-01-31 16:28:34.737767-05	test	2021-01-31 19:03:44.011051-05	test	In Kubernetes, A ConfigMap is an API object used to store non-confidential data in key-value pairs. Pods can consume ConfigMaps as environment variables, command-line arguments, or as configuration files in a volume.	imbi kubernetes
SSM Parameter Store	2021-01-31 16:29:23.44755-05	test	2021-02-02 18:17:47.683775-05	gavinr	AWS Systems Manager Parameter Store provides secure, hierarchical storage for configuration data management and secrets management.	fab aws
\.


--
-- Data for Name: project_types; Type: TABLE DATA; Schema: v1; Owner: imbi
--

COPY v1.project_types (id, created_at, created_by, last_modified_at, last_modified_by, name, description, slug, icon_class) FROM stdin;
1	2021-01-31 16:34:36.095645-05	test	2021-01-31 16:42:14.378736-05	test	RESTful API	A RESTful API is an architectural style for an application program interface (API) that uses HTTP requests to access and use data. That data can be used to GET, PATCH, PUT, POST and DELETE data types, which refers to the reading, updating, creating and deleting of operations concerning resources.	restful-api	fas server
2	2021-01-31 17:20:49.826185-05	test	\N	\N	Rundeck Job	A job that is orchestrated or run from a RunDeck server	job	imbi rundeck
4	2021-01-31 17:22:05.018478-05	test	\N	\N	Programming Library	A library is a collection of non-volatile resources used by computer programs, often for software development. These may include configuration data, documentation, help data, message templates, pre-written code and subroutines, classes, values or type specifications.	library	fas folder
5	2021-01-31 17:24:15.564168-05	test	2021-01-31 17:42:59.287368-05	test	Browser-Based Application	A browser-based (or web-based) tool, application, program, or app is software that runs on your web browser.	browser-app	fas desktop
6	2021-01-31 17:25:52.275488-05	test	\N	\N	Web Application	A web application is application software that runs on a web server, unlike computer-based software programs that are run locally on the operating system of the device. Web applications are accessed by the user through a web browser with an active internet connection.	web-app	fas server
7	2021-01-31 17:26:33.638621-05	test	\N	\N	Mobile Application	A mobile application, also referred to as a mobile app or simply an app, is a computer program or software application designed to run on a mobile device such as a phone, tablet, or watch.	mobile-app	fas mobile-alt
8	2021-02-03 10:15:36.251273-05	gavinr	\N	\N	Other	Projects that do not fall into any of the other categories	other	fas question-circle
9	2021-02-03 10:24:10.943509-05	gavinr	\N	\N	Static Website	A static website that is generated using a website generation tool.	website	fas magic
10	2021-02-03 10:45:40.931883-05	gavinr	\N	\N	Service	A service is an internally run, but not maintained, application. For example, Kong Proxies, Varnish, Consul, Vault, Grafana, Imbi, RabbitMQ, and similar applications are categorized as services.	service	fas cubes
11	2021-02-03 17:37:31.088648-05	gavinr	\N	\N	Database	A database, such as AppDB, Analytics Broker, etc.	database	fas database
12	2021-02-03 17:37:54.775911-05	gavinr	\N	\N	RabbitMQ Cluster	A RabbitMQ Cluster	rabbitmq	imbi rabbitmq
3	2021-01-31 17:21:16.730219-05	test	2021-02-03 17:38:12.649078-05	gavinr	Consumer	A RabbitMQ consumer application	consumer	imbi rabbitmq
\.


--
-- Data for Name: cookie_cutters; Type: TABLE DATA; Schema: v1; Owner: imbi
--

COPY v1.cookie_cutters (name, created_at, created_by, last_modified_at, last_modified_by, description, type, project_type_id, url) FROM stdin;
Integrations api-cookiecutter	2021-01-31 18:06:29.266591-05	test	2021-01-31 18:51:55.217286-05	test	A RestFUL API cookie cutter maintained by the Integrations team	project	1	https://gitlab.aweber.io/integrations/cookiecutters/api-cookiecutter.git
Integrations consumer-cookiecutter	2021-01-31 18:14:35.351608-05	test	2021-01-31 18:14:50.0699-05	test	A RabbitMQ Consumer cookie cutter maintained by the Integrations team.	project	3	https://gitlab.aweber.io/integrations/cookiecutters/consumer-cookiecutter.git
\.


--
-- Data for Name: data_centers; Type: TABLE DATA; Schema: v1; Owner: imbi
--

COPY v1.data_centers (name, created_at, created_by, last_modified_at, last_modified_by, description, icon_class) FROM stdin;
MDF	2021-01-31 18:18:49.639049-05	test	\N	\N	AWeber MDF in Chalfont	fas building
us-east-1	2021-01-31 18:18:17.765311-05	test	2021-01-31 18:20:32.221941-05	test	Amazon US East 1 (Northern Virginia)	fab aws
\.


--
-- Data for Name: deployment_types; Type: TABLE DATA; Schema: v1; Owner: imbi
--

COPY v1.deployment_types (name, created_at, created_by, last_modified_at, last_modified_by, description, icon_class) FROM stdin;
Jenkins	2021-01-31 18:21:28.005397-05	test	\N	\N	Deployments via Jenkins	fab jenkins
Rundeck	2021-01-31 18:23:42.575117-05	test	\N	\N	Deployments to Virtual Machines using Rundeck	imbi rundeck
Helm	2021-01-31 18:21:04.528213-05	test	2021-01-31 19:03:20.580693-05	test	Deployments to Kubernetes via Helm using GitLab CI	imbi kubernetes
ECS Pipeline Deploy	2021-01-31 18:23:10.508565-05	test	2021-01-31 19:03:31.192911-05	test	Deployments to ECS using ecs-pipeline-deploy in GitLab CI	fab aws
\.


--
-- Data for Name: environments; Type: TABLE DATA; Schema: v1; Owner: imbi
--

COPY v1.environments (name, created_at, created_by, last_modified_at, last_modified_by, description, icon_class) FROM stdin;
Testing	2021-01-31 18:26:11.852021-05	test	\N	\N	The testing environment reflects the state of the main or master branch of our applications in git.	fas hard-hat
Staging	2021-01-31 18:26:54.916666-05	test	\N	\N	The staging environment reflects the most recently tagged version of our applications that may or may not have been deployed to production.	fas tags
Production	2021-01-31 18:27:44.065684-05	test	\N	\N	The production environment is what serves the AWeber application to our customers.	fas traffic-light
Sandbox	2021-01-31 18:30:17.562468-05	test	\N	\N	The sandbox environment is for experimentation and R&D	fas flask
Infrastructure	2021-01-31 18:28:45.692905-05	test	2021-01-31 18:35:04.549862-05	test	The infrastructure environment is for internal applications and services that support AWeber applications across all environments.	fas road
\.


--
-- Data for Name: groups; Type: TABLE DATA; Schema: v1; Owner: imbi
--

COPY v1.groups (name, created_at, created_by, last_modified_at, last_modified_by, group_type, external_id, permissions) FROM stdin;
allhands	2021-02-02 15:01:43.226323-05	system	\N	\N	ldap	cn=allhands,cn=groups,cn=accounts,dc=aweberint,dc=com	{user}
dba	2021-02-02 15:01:43.226323-05	system	\N	\N	ldap	cn=dba,cn=groups,cn=accounts,dc=aweberint,dc=com	{user}
dbas	2021-02-02 15:01:43.226323-05	system	\N	\N	ldap	cn=dbas,cn=groups,cn=accounts,dc=aweberint,dc=com	{user}
employees	2021-02-02 15:01:43.226323-05	system	\N	\N	ldap	cn=employees,cn=groups,cn=accounts,dc=aweberint,dc=com	{user}
internal-consulting	2021-02-02 15:01:43.226323-05	system	\N	\N	ldap	cn=internal-consulting,cn=groups,cn=accounts,dc=aweberint,dc=com	{user}
ipausers	2021-02-02 15:01:43.226323-05	system	\N	\N	ldap	cn=ipausers,cn=groups,cn=accounts,dc=aweberint,dc=com	{user}
ismanager	2021-02-02 15:01:43.226323-05	system	\N	\N	ldap	cn=ismanager,cn=groups,cn=accounts,dc=aweberint,dc=com	{user}
managers	2021-02-02 15:01:43.226323-05	system	\N	\N	ldap	cn=managers,cn=groups,cn=accounts,dc=aweberint,dc=com	{user}
momentum-config	2021-02-02 15:01:43.226323-05	system	\N	\N	ldap	cn=momentum-config,cn=groups,cn=accounts,dc=aweberint,dc=com	{user}
navrecorder-admins	2021-02-02 15:01:43.226323-05	system	\N	\N	ldap	cn=navrecorder-admins,cn=groups,cn=accounts,dc=aweberint,dc=com	{user}
rundeck	2021-02-02 15:01:43.226323-05	system	\N	\N	ldap	cn=rundeck,cn=groups,cn=accounts,dc=aweberint,dc=com	{user}
sonarqube-admins	2021-02-02 15:01:43.226323-05	system	\N	\N	ldap	cn=sonarqube-admins,cn=groups,cn=accounts,dc=aweberint,dc=com	{user}
sysadmins	2021-02-02 15:01:43.226323-05	system	\N	\N	ldap	cn=sysadmins,cn=groups,cn=accounts,dc=aweberint,dc=com	{user}
techmanagers	2021-02-02 15:01:43.226323-05	system	\N	\N	ldap	cn=techmanagers,cn=groups,cn=accounts,dc=aweberint,dc=com	{user}
technical	2021-02-02 15:01:43.226323-05	system	\N	\N	ldap	cn=technical,cn=groups,cn=accounts,dc=aweberint,dc=com	{user}
tectonic-admins	2021-02-02 15:01:43.226323-05	system	\N	\N	ldap	cn=tectonic-admins,cn=groups,cn=accounts,dc=aweberint,dc=com	{user}
vault-admins	2021-02-02 15:01:43.226323-05	system	\N	\N	ldap	cn=vault-admins,cn=groups,cn=accounts,dc=aweberint,dc=com	{user}
vpnaccess	2021-02-02 15:01:43.226323-05	system	\N	\N	ldap	cn=vpnaccess,cn=groups,cn=accounts,dc=aweberint,dc=com	{user}
vpnallowed	2021-02-02 15:01:43.226323-05	system	\N	\N	ldap	cn=vpnallowed,cn=groups,cn=accounts,dc=aweberint,dc=com	{user}
pse	2021-02-02 15:01:43.226323-05	system	\N	\N	ldap	cn=pse,cn=groups,cn=accounts,dc=aweberint,dc=com	{admin,user}
\.


--
-- Data for Name: group_members; Type: TABLE DATA; Schema: v1; Owner: imbi
--

COPY v1.group_members ("group", username) FROM stdin;
allhands	gavinr
dba	gavinr
dbas	gavinr
employees	gavinr
internal-consulting	gavinr
ipausers	gavinr
ismanager	gavinr
managers	gavinr
momentum-config	gavinr
navrecorder-admins	gavinr
pse	gavinr
rundeck	gavinr
sonarqube-admins	gavinr
sysadmins	gavinr
techmanagers	gavinr
technical	gavinr
tectonic-admins	gavinr
vault-admins	gavinr
vpnaccess	gavinr
vpnallowed	gavinr
\.


--
-- Data for Name: namespaces; Type: TABLE DATA; Schema: v1; Owner: imbi
--

COPY v1.namespaces (id, created_at, created_by, last_modified_at, last_modified_by, name, slug, icon_class, maintained_by) FROM stdin;
7	2021-02-03 10:20:56.964259-05	gavinr	\N	\N	Cardholder Data Environment	CDE	fas credit-card	{}
8	2021-02-03 10:21:30.92539-05	gavinr	\N	\N	Database Administration	DBA	fas database	{dba,dbas}
1	2021-01-31 18:51:25.781837-05	test	2021-02-03 10:21:46.487042-05	gavinr	Application Support Engineering	ASE	fas life-ring	{}
2	2021-01-31 18:37:22.295315-05	test	2021-02-03 10:21:51.479335-05	gavinr	Content Creation	CC	fas paint-brush	{}
3	2021-01-31 18:49:40.252095-05	test	2021-02-03 10:21:56.902669-05	gavinr	Control Panel	CP	fas laptop-code	{}
4	2021-01-31 18:50:11.395808-05	test	2021-02-03 10:22:10.258309-05	gavinr	Email Delivery	EDELIV	fas envelope	{}
5	2021-01-31 18:50:36.882933-05	test	2021-02-03 10:22:16.142448-05	gavinr	Integrations	INT	fas puzzle-piece	{}
6	2021-01-31 18:36:22.205869-05	test	2021-02-03 10:22:21.250592-05	gavinr	Platform Support Engineering	PSE	fas hard-hat	{pse}
\.


--
-- Data for Name: orchestration_systems; Type: TABLE DATA; Schema: v1; Owner: imbi
--

COPY v1.orchestration_systems (name, created_at, created_by, last_modified_at, last_modified_by, description, icon_class) FROM stdin;
Kubernetes	2021-01-31 19:02:57.108744-05	test	2021-01-31 19:04:01.478932-05	test	Kubernetes is an open-source container-orchestration system for automating computer application deployment, scaling, and management.	imbi kubernetes
ECS	2021-02-02 15:49:19.317346-05	gavinr	\N	\N	Amazon Elastic Container Service	fab aws
\.


--
-- Data for Name: projects; Type: TABLE DATA; Schema: v1; Owner: imbi
--

COPY v1.projects (id, namespace_id, project_type_id, created_at, created_by, last_modified_at, last_modified_by, name, slug, description, data_center, environments, configuration_system, deployment_type, orchestration_system) FROM stdin;
1	6	6	2021-02-02 15:42:07.259338-05	gavinr	\N	\N	Imbi	imbi	Imbi is a DevOps Service Management Platform designed to provide an efficient way to manage a large environment that contains many services and applications.	MDF	{Infrastructure,Sandbox}	Consul	Helm	Kubernetes
2	6	1	2021-02-02 15:51:21.284676-05	gavinr	\N	\N	Analytics Broker	anabroker	Provides account to database lookup for Analytics Databases	us-east-1	{Production,Staging,Testing}	SSM Parameter Store	ECS Pipeline Deploy	ECS
3	6	3	2021-02-02 19:31:12.447888-05	gavinr	\N	\N	Analytics Consumers	anadb-consumers	Analytics Consumers	MDF	{Production,Staging,Testing}	Consul	Helm	Kubernetes
\.


--
-- Data for Name: project_dependencies; Type: TABLE DATA; Schema: v1; Owner: imbi
--

COPY v1.project_dependencies (project_id, dependency_id, created_at, created_by) FROM stdin;
\.


--
-- Data for Name: project_fact_types; Type: TABLE DATA; Schema: v1; Owner: imbi
--

COPY v1.project_fact_types (id, created_at, created_by, last_modified_at, last_modified_by, project_type_id, fact_type, weight) FROM stdin;
1	2021-01-31 19:07:24.41556-05	test	2021-01-31 19:07:45.08432-05	test	1	Programming Language	30
2	2021-01-31 19:10:39.763978-05	test	\N	\N	1	Test Coverage	25
\.


--
-- Data for Name: project_fact_history; Type: TABLE DATA; Schema: v1; Owner: imbi
--

COPY v1.project_fact_history (project_id, fact_type_id, recorded_at, recorded_by, value, score, weight) FROM stdin;
\.


--
-- Data for Name: project_fact_type_options; Type: TABLE DATA; Schema: v1; Owner: imbi
--

COPY v1.project_fact_type_options (id, created_at, created_by, last_modified_at, last_modified_by, fact_type_id, value, score) FROM stdin;
\.


--
-- Data for Name: project_facts; Type: TABLE DATA; Schema: v1; Owner: imbi
--

COPY v1.project_facts (project_id, fact_type_id, created_at, created_by, last_modified_at, last_modified_by, value) FROM stdin;
\.


--
-- Data for Name: project_link_types; Type: TABLE DATA; Schema: v1; Owner: imbi
--

COPY v1.project_link_types (id, created_at, created_by, last_modified_at, last_modified_by, link_type, icon_class) FROM stdin;
1	2021-01-31 19:11:04.162806-05	test	\N	\N	GitLab Repository	fab gitlab
2	2021-01-31 19:11:31.827179-05	test	\N	\N	Grafana Dashboard	fas chart-line
3	2021-01-31 19:11:50.531043-05	test	2021-01-31 19:28:22.04299-05	test	Documentation	fas book
4	2021-01-31 19:14:46.283277-05	test	\N	\N	Sentry	imbi sentry
5	2021-02-03 15:31:18.299772-05	gavinr	\N	\N	SonarQube	imbi sonarqube
\.


--
-- Data for Name: project_links; Type: TABLE DATA; Schema: v1; Owner: imbi
--

COPY v1.project_links (project_id, link_type_id, created_at, created_by, last_modified_at, last_modified_by, url) FROM stdin;
1	1	2021-02-02 15:42:08.039404-05	gavinr	\N	\N	https://gitlab.aweber.io/PSE/Services/imbi
1	2	2021-02-02 15:42:08.811562-05	gavinr	\N	\N	https://grafana.aweber.io/d/000000296/home-dashboard?orgId=1
1	3	2021-02-02 15:42:10.531089-05	gavinr	\N	\N	https://imbi.readthedocs.org
1	4	2021-02-02 15:42:11.313994-05	gavinr	\N	\N	https://sentry.io/organizations/aweber-communications/issues/?project=5619880
2	1	2021-02-02 15:51:22.059312-05	gavinr	\N	\N	https://gitlab.aweber.io/PSE/Applications/anabroker
2	2	2021-02-02 15:51:22.792736-05	gavinr	\N	\N	https://grafana.aweber.io/d/9BFEDX9iz/anabroker-service
2	3	2021-02-02 15:51:23.544407-05	gavinr	\N	\N	https://anabroker.aweberprod.com
2	4	2021-02-02 15:51:24.291105-05	gavinr	\N	\N	https://sentry.io/organizations/aweber-communications/issues/?project=1132504
3	1	2021-02-02 19:31:13.302565-05	gavinr	\N	\N	https://gitlab.aweber.io/PSE/Applications/anadb-consumers
3	2	2021-02-02 19:31:14.00148-05	gavinr	\N	\N	https://grafana.aweber.io/d/000000229/analytics-processing
3	4	2021-02-02 19:31:14.754608-05	gavinr	\N	\N	https://sentry.io/organizations/aweber-communications/issues/?project=103966
\.


--
-- Name: namespaces_id_seq; Type: SEQUENCE SET; Schema: v1; Owner: imbi
--

SELECT pg_catalog.setval('v1.namespaces_id_seq', 8, true);


--
-- Name: project_fact_type_options_id_seq; Type: SEQUENCE SET; Schema: v1; Owner: imbi
--

SELECT pg_catalog.setval('v1.project_fact_type_options_id_seq', 1, false);


--
-- Name: project_fact_types_id_seq; Type: SEQUENCE SET; Schema: v1; Owner: imbi
--

SELECT pg_catalog.setval('v1.project_fact_types_id_seq', 2, true);


--
-- Name: project_link_types_id_seq; Type: SEQUENCE SET; Schema: v1; Owner: imbi
--

SELECT pg_catalog.setval('v1.project_link_types_id_seq', 5, true);


--
-- Name: project_types_id_seq; Type: SEQUENCE SET; Schema: v1; Owner: imbi
--

SELECT pg_catalog.setval('v1.project_types_id_seq', 12, true);


--
-- Name: projects_id_seq; Type: SEQUENCE SET; Schema: v1; Owner: imbi
--

SELECT pg_catalog.setval('v1.projects_id_seq', 3, true);


--
-- PostgreSQL database dump complete
--

