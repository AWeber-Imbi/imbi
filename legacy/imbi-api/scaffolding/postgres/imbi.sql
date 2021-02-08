--
-- PostgreSQL database dump
--

-- Dumped from database version 13.1
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
-- Data for Name: users; Type: TABLE DATA; Schema: v1; Owner: postgres
--

COPY v1.users (username, created_at, last_seen_at, user_type, external_id, email_address, display_name, password) FROM stdin;
ffink	2021-02-07 17:36:04.053741+00	\N	ldap	cn=ffink,ou=users,dc=example,dc=org	ffink@frank-jewelry.com	Frank	\N
gavinr	2021-02-02 20:01:43.172148+00	2021-02-06 18:17:09.11881+00	ldap	uid=gavinr,cn=users,cn=accounts,dc=aweberint,dc=com	gavinr@aweber.com	Gavin Roy	\N
test	2021-02-07 17:36:04.051216+00	2021-02-07 17:48:01.288383+00	ldap	cn=test,ou=users,dc=example,dc=org	imbi@example.org	Its Imbi	\N
\.


--
-- Data for Name: authentication_tokens; Type: TABLE DATA; Schema: v1; Owner: postgres
--

COPY v1.authentication_tokens (token, username, name, created_at, expires_at, last_used_at) FROM stdin;
01777d94-86cf-f3b3-b891-4c4d9128c7d5	test	Import	2021-02-07 17:40:21.841271+00	2022-02-07 17:40:21.841271+00	\N
\.


--
-- Data for Name: configuration_systems; Type: TABLE DATA; Schema: v1; Owner: postgres
--

COPY v1.configuration_systems (name, created_at, created_by, last_modified_at, last_modified_by, description, icon_class) FROM stdin;
Consul	2021-01-31 21:17:10.132596+00	test	2021-01-31 21:23:53.870839+00	test	Consul provides DNS-based service discovery and distributed Key-value storage, segmentation and configuration. Registered services and nodes can be queried using a DNS interface or an HTTP interface.	imbi consul
Ansible	2021-01-31 21:25:49.591641+00	test	\N	\N	Ansible is an open-source software provisioning, configuration management, and application-deployment tool enabling infrastructure as code.	imbi ansible
Chef	2021-01-31 21:27:10.4064+00	test	\N	\N	Chef is a configuration management tool written in Ruby and Erlang. It uses a pure-Ruby, domain-specific language for writing system configuration "recipes".	fas sliders-h
Puppet	2021-01-31 21:27:32.257247+00	test	\N	\N	Puppet is a software configuration management tool which includes its own declarative language to describe system configuration.	fas sliders-h
Kubernetes Config Map	2021-01-31 21:28:34.737767+00	test	2021-02-01 00:03:44.011051+00	test	In Kubernetes, A ConfigMap is an API object used to store non-confidential data in key-value pairs. Pods can consume ConfigMaps as environment variables, command-line arguments, or as configuration files in a volume.	imbi kubernetes
SSM Parameter Store	2021-01-31 21:29:23.44755+00	test	2021-02-02 23:17:47.683775+00	gavinr	AWS Systems Manager Parameter Store provides secure, hierarchical storage for configuration data management and secrets management.	fab aws
\.


--
-- Data for Name: project_types; Type: TABLE DATA; Schema: v1; Owner: postgres
--

COPY v1.project_types (id, created_at, created_by, last_modified_at, last_modified_by, name, slug, plural_name, description, icon_class) FROM stdin;
5	2021-01-31 22:24:15.564168+00	test	2021-02-07 17:44:25.640387+00	test	Browser-Based Application	browser-app	Browser-Based Applications	A browser-based (or web-based) tool, application, program, or app is software that runs on your web browser.	fas desktop
3	2021-01-31 22:21:16.730219+00	test	2021-02-07 17:44:31.992131+00	test	Consumer	consumer	Consumers	A RabbitMQ consumer application	imbi rabbitmq
11	2021-02-03 22:37:31.088648+00	gavinr	2021-02-07 17:44:37.194649+00	test	Database	database	Databases	A database, such as AppDB, Analytics Broker, etc.	fas database
7	2021-01-31 22:26:33.638621+00	test	2021-02-07 17:44:41.869293+00	test	Mobile Application	mobile-app	Mobile Applications	A mobile application, also referred to as a mobile app or simply an app, is a computer program or software application designed to run on a mobile device such as a phone, tablet, or watch.	fas mobile-alt
8	2021-02-03 15:15:36.251273+00	gavinr	2021-02-07 17:45:04.516396+00	test	Other	other	Other Applications	Projects that do not fall into any of the other categories	fas question-circle
4	2021-01-31 22:22:05.018478+00	test	2021-02-07 17:45:13.86201+00	test	Programming Library	library	Programming Libraries	A library is a collection of non-volatile resources used by computer programs, often for software development. These may include configuration data, documentation, help data, message templates, pre-written code and subroutines, classes, values or type specifications.	fas folder
1	2021-01-31 21:34:36.095645+00	test	2021-02-07 17:45:20.586681+00	test	RESTful API	restful-api	RESTful APIs	A RESTful API is an architectural style for an application program interface (API) that uses HTTP requests to access and use data. That data can be used to GET, PATCH, PUT, POST and DELETE data types, which refers to the reading, updating, creating and deleting of operations concerning resources.	fas server
12	2021-02-03 22:37:54.775911+00	gavinr	2021-02-07 17:45:25.679715+00	test	RabbitMQ Cluster	rabbitmq	RabbitMQ Clusters	A RabbitMQ Cluster	imbi rabbitmq
2	2021-01-31 22:20:49.826185+00	test	2021-02-07 17:45:32.521472+00	test	Rundeck Job	job	Rundeck Jobs	A job that is orchestrated or run from a RunDeck server	imbi rundeck
10	2021-02-03 15:45:40.931883+00	gavinr	2021-02-07 17:45:37.904569+00	test	Service	service	Services	A service is an internally run, but not maintained, application. For example, Kong Proxies, Varnish, Consul, Vault, Grafana, Imbi, RabbitMQ, and similar applications are categorized as services.	fas cubes
9	2021-02-03 15:24:10.943509+00	gavinr	2021-02-07 17:45:43.612585+00	test	Static Website	website	Static Websites	A static website that is generated using a website generation tool.	fas magic
6	2021-01-31 22:25:52.275488+00	test	2021-02-07 17:45:48.438081+00	test	Web Application	web-app	Web Applications	A web application is application software that runs on a web server, unlike computer-based software programs that are run locally on the operating system of the device. Web applications are accessed by the user through a web browser with an active internet connection.	fas server
\.


--
-- Data for Name: cookie_cutters; Type: TABLE DATA; Schema: v1; Owner: postgres
--

COPY v1.cookie_cutters (name, created_at, created_by, last_modified_at, last_modified_by, description, type, project_type_id, url) FROM stdin;
Integrations api-cookiecutter	2021-01-31 23:06:29.266591+00	test	2021-01-31 23:51:55.217286+00	test	A RestFUL API cookie cutter maintained by the Integrations team	project	1	https://gitlab.aweber.io/integrations/cookiecutters/api-cookiecutter.git
Integrations consumer-cookiecutter	2021-01-31 23:14:35.351608+00	test	2021-01-31 23:14:50.0699+00	test	A RabbitMQ Consumer cookie cutter maintained by the Integrations team.	project	3	https://gitlab.aweber.io/integrations/cookiecutters/consumer-cookiecutter.git
\.


--
-- Data for Name: data_centers; Type: TABLE DATA; Schema: v1; Owner: postgres
--

COPY v1.data_centers (name, created_at, created_by, last_modified_at, last_modified_by, description, icon_class) FROM stdin;
MDF	2021-01-31 23:18:49.639049+00	test	\N	\N	AWeber MDF in Chalfont	fas building
us-east-1	2021-01-31 23:18:17.765311+00	test	2021-01-31 23:20:32.221941+00	test	Amazon US East 1 (Northern Virginia)	fab aws
\.


--
-- Data for Name: deployment_types; Type: TABLE DATA; Schema: v1; Owner: postgres
--

COPY v1.deployment_types (name, created_at, created_by, last_modified_at, last_modified_by, description, icon_class) FROM stdin;
Jenkins	2021-01-31 23:21:28.005397+00	test	\N	\N	Deployments via Jenkins	fab jenkins
Rundeck	2021-01-31 23:23:42.575117+00	test	\N	\N	Deployments to Virtual Machines using Rundeck	imbi rundeck
Helm	2021-01-31 23:21:04.528213+00	test	2021-02-01 00:03:20.580693+00	test	Deployments to Kubernetes via Helm using GitLab CI	imbi kubernetes
ECS Pipeline Deploy	2021-01-31 23:23:10.508565+00	test	2021-02-01 00:03:31.192911+00	test	Deployments to ECS using ecs-pipeline-deploy in GitLab CI	fab aws
GitLab CI	2021-02-07 17:43:58.987494+00	test	2021-02-07 17:47:09.671243+00	test	Deployments using the Gitlab CI pipeline exclusively	fab gitlab
\.


--
-- Data for Name: environments; Type: TABLE DATA; Schema: v1; Owner: postgres
--

COPY v1.environments (name, created_at, created_by, last_modified_at, last_modified_by, description, icon_class) FROM stdin;
Testing	2021-01-31 23:26:11.852021+00	test	\N	\N	The testing environment reflects the state of the main or master branch of our applications in git.	fas hard-hat
Staging	2021-01-31 23:26:54.916666+00	test	\N	\N	The staging environment reflects the most recently tagged version of our applications that may or may not have been deployed to production.	fas tags
Production	2021-01-31 23:27:44.065684+00	test	\N	\N	The production environment is what serves the AWeber application to our customers.	fas traffic-light
Sandbox	2021-01-31 23:30:17.562468+00	test	\N	\N	The sandbox environment is for experimentation and R&D	fas flask
Infrastructure	2021-01-31 23:28:45.692905+00	test	2021-01-31 23:35:04.549862+00	test	The infrastructure environment is for internal applications and services that support AWeber applications across all environments.	fas road
\.


--
-- Data for Name: groups; Type: TABLE DATA; Schema: v1; Owner: postgres
--

COPY v1.groups (name, created_at, created_by, last_modified_at, last_modified_by, group_type, external_id, permissions) FROM stdin;
admin	2021-02-07 17:36:04.044315+00	system	\N	\N	ldap	cn=admin,ou=groups,dc=example,dc=org	{admin}
imbi	2021-02-07 17:36:04.048537+00	system	\N	\N	ldap	cn=imbi,ou=groups,dc=example,dc=org	{reader}
allhands	2021-02-02 20:01:43.226323+00	system	\N	\N	ldap	cn=allhands,cn=groups,cn=accounts,dc=aweberint,dc=com	{user}
dba	2021-02-02 20:01:43.226323+00	system	\N	\N	ldap	cn=dba,cn=groups,cn=accounts,dc=aweberint,dc=com	{user}
dbas	2021-02-02 20:01:43.226323+00	system	\N	\N	ldap	cn=dbas,cn=groups,cn=accounts,dc=aweberint,dc=com	{user}
employees	2021-02-02 20:01:43.226323+00	system	\N	\N	ldap	cn=employees,cn=groups,cn=accounts,dc=aweberint,dc=com	{user}
internal-consulting	2021-02-02 20:01:43.226323+00	system	\N	\N	ldap	cn=internal-consulting,cn=groups,cn=accounts,dc=aweberint,dc=com	{user}
ipausers	2021-02-02 20:01:43.226323+00	system	\N	\N	ldap	cn=ipausers,cn=groups,cn=accounts,dc=aweberint,dc=com	{user}
ismanager	2021-02-02 20:01:43.226323+00	system	\N	\N	ldap	cn=ismanager,cn=groups,cn=accounts,dc=aweberint,dc=com	{user}
managers	2021-02-02 20:01:43.226323+00	system	\N	\N	ldap	cn=managers,cn=groups,cn=accounts,dc=aweberint,dc=com	{user}
momentum-config	2021-02-02 20:01:43.226323+00	system	\N	\N	ldap	cn=momentum-config,cn=groups,cn=accounts,dc=aweberint,dc=com	{user}
navrecorder-admins	2021-02-02 20:01:43.226323+00	system	\N	\N	ldap	cn=navrecorder-admins,cn=groups,cn=accounts,dc=aweberint,dc=com	{user}
rundeck	2021-02-02 20:01:43.226323+00	system	\N	\N	ldap	cn=rundeck,cn=groups,cn=accounts,dc=aweberint,dc=com	{user}
sonarqube-admins	2021-02-02 20:01:43.226323+00	system	\N	\N	ldap	cn=sonarqube-admins,cn=groups,cn=accounts,dc=aweberint,dc=com	{user}
sysadmins	2021-02-02 20:01:43.226323+00	system	\N	\N	ldap	cn=sysadmins,cn=groups,cn=accounts,dc=aweberint,dc=com	{user}
techmanagers	2021-02-02 20:01:43.226323+00	system	\N	\N	ldap	cn=techmanagers,cn=groups,cn=accounts,dc=aweberint,dc=com	{user}
technical	2021-02-02 20:01:43.226323+00	system	\N	\N	ldap	cn=technical,cn=groups,cn=accounts,dc=aweberint,dc=com	{user}
tectonic-admins	2021-02-02 20:01:43.226323+00	system	\N	\N	ldap	cn=tectonic-admins,cn=groups,cn=accounts,dc=aweberint,dc=com	{user}
vault-admins	2021-02-02 20:01:43.226323+00	system	\N	\N	ldap	cn=vault-admins,cn=groups,cn=accounts,dc=aweberint,dc=com	{user}
vpnaccess	2021-02-02 20:01:43.226323+00	system	\N	\N	ldap	cn=vpnaccess,cn=groups,cn=accounts,dc=aweberint,dc=com	{user}
vpnallowed	2021-02-02 20:01:43.226323+00	system	\N	\N	ldap	cn=vpnallowed,cn=groups,cn=accounts,dc=aweberint,dc=com	{user}
pse	2021-02-02 20:01:43.226323+00	system	\N	\N	ldap	cn=pse,cn=groups,cn=accounts,dc=aweberint,dc=com	{admin,user}
\.


--
-- Data for Name: group_members; Type: TABLE DATA; Schema: v1; Owner: postgres
--

COPY v1.group_members ("group", username) FROM stdin;
admin	test
imbi	ffink
imbi	test
\.


--
-- Data for Name: namespaces; Type: TABLE DATA; Schema: v1; Owner: postgres
--

COPY v1.namespaces (id, created_at, created_by, last_modified_at, last_modified_by, name, slug, icon_class, maintained_by) FROM stdin;
7	2021-02-03 15:20:56.964259+00	gavinr	\N	\N	Cardholder Data Environment	CDE	fas credit-card	{}
8	2021-02-03 15:21:30.92539+00	gavinr	\N	\N	Database Administration	DBA	fas database	{dba,dbas}
1	2021-01-31 23:51:25.781837+00	test	2021-02-03 15:21:46.487042+00	gavinr	Application Support Engineering	ASE	fas life-ring	{}
2	2021-01-31 23:37:22.295315+00	test	2021-02-03 15:21:51.479335+00	gavinr	Content Creation	CC	fas paint-brush	{}
3	2021-01-31 23:49:40.252095+00	test	2021-02-03 15:21:56.902669+00	gavinr	Control Panel	CP	fas laptop-code	{}
4	2021-01-31 23:50:11.395808+00	test	2021-02-03 15:22:10.258309+00	gavinr	Email Delivery	EDELIV	fas envelope	{}
5	2021-01-31 23:50:36.882933+00	test	2021-02-03 15:22:16.142448+00	gavinr	Integrations	INT	fas puzzle-piece	{}
6	2021-01-31 23:36:22.205869+00	test	2021-02-03 15:22:21.250592+00	gavinr	Platform Support Engineering	PSE	fas hard-hat	{pse}
9	2021-02-07 17:41:10.444434+00	test	\N	\N	Conversions	CONV	fas funnel-dollar	{}
10	2021-02-07 17:41:36.107969+00	test	\N	\N	Front-End BoF	FEBOF	fas feather	{}
\.


--
-- Data for Name: orchestration_systems; Type: TABLE DATA; Schema: v1; Owner: postgres
--

COPY v1.orchestration_systems (name, created_at, created_by, last_modified_at, last_modified_by, description, icon_class) FROM stdin;
Kubernetes	2021-02-01 00:02:57.108744+00	test	2021-02-01 00:04:01.478932+00	test	Kubernetes is an open-source container-orchestration system for automating computer application deployment, scaling, and management.	imbi kubernetes
ECS	2021-02-02 20:49:19.317346+00	gavinr	\N	\N	Amazon Elastic Container Service	fab aws
ECS (1st Gen)	2021-02-07 17:42:17.211666+00	test	\N	\N	AWeber's 1st Generation AWS ECS Cluster	fab aws
Rundeck	2021-02-07 17:43:24.006614+00	test	\N	\N	Rundeck is an open source automation service with a web console, command line tools and a WebAPI.	imbi rundeck
\.


--
-- Data for Name: projects; Type: TABLE DATA; Schema: v1; Owner: postgres
--

COPY v1.projects (id, namespace_id, project_type_id, created_at, created_by, last_modified_at, last_modified_by, name, slug, description, data_center, environments, configuration_system, deployment_type, orchestration_system) FROM stdin;
1	6	6	2021-02-02 20:42:07.259338+00	gavinr	\N	\N	Imbi	imbi	Imbi is a DevOps Service Management Platform designed to provide an efficient way to manage a large environment that contains many services and applications.	MDF	{Infrastructure,Sandbox}	Consul	Helm	Kubernetes
636	1	2	2021-02-07 17:47:17.627293+00	test	\N	\N	sync_zendesk_jira	sync_zendesk_jira	\N	MDF	{Staging,Production}	Chef	Jenkins	\N
637	2	1	2021-02-07 17:47:17.698801+00	test	\N	\N	Broadcast Archive	broadcast-archive	\N	MDF	{Testing,Staging,Production}	Consul	Helm	Kubernetes
638	2	1	2021-02-07 17:47:17.774148+00	test	\N	\N	Broadcast Scheduling	broadcast-scheduling	\N	MDF	{Testing,Staging,Production}	Consul	Helm	Kubernetes
639	2	1	2021-02-07 17:47:17.937165+00	test	\N	\N	Campaign	campaign	\N	us-east-1	{Testing,Staging,Production}	SSM Parameter Store	ECS Pipeline Deploy	ECS
644	2	1	2021-02-07 17:47:18.726224+00	test	\N	\N	Customer Export	customer-export	\N	MDF	{Staging,Production}	Consul	Helm	Kubernetes
645	2	8	2021-02-07 17:47:18.879997+00	test	\N	\N	Feed Processor	feed-processor	\N	MDF	{Staging,Production}	Chef	Jenkins	\N
648	2	1	2021-02-07 17:47:19.275652+00	test	\N	\N	Image Proxy	imageproxy	\N	MDF	{Staging,Production}	Puppet	Jenkins	\N
649	2	1	2021-02-07 17:47:19.365211+00	test	\N	\N	Message	message	\N	MDF	{Testing,Staging,Production}	Consul	Helm	Kubernetes
650	2	1	2021-02-07 17:47:19.522645+00	test	\N	\N	Message Statistics	message-statistics	\N	MDF	\N	Chef	Jenkins	\N
651	2	1	2021-02-07 17:47:19.678573+00	test	\N	\N	Message Editor API	messageeditorapi	\N	MDF	{Staging,Production}	Chef	Jenkins	\N
654	2	1	2021-02-07 17:47:20.113073+00	test	\N	\N	Rule	rule	\N	us-east-1	\N	SSM Parameter Store	ECS Pipeline Deploy	ECS
656	2	8	2021-02-07 17:47:20.533768+00	test	\N	\N	Scheduler Publisher	scheduler-publisher	\N	MDF	{Testing,Staging,Production}	Consul	Helm	Kubernetes
663	2	8	2021-02-07 17:47:21.404818+00	test	\N	\N	Web Content Gateway	web-content-gateway	\N	MDF	{Testing,Staging,Production}	Consul	Helm	Kubernetes
689	2	5	2021-02-07 17:47:23.594018+00	test	\N	\N	campaign-builder	campaign-builder	\N	MDF	{Testing,Staging,Production}	Puppet	Jenkins	\N
692	2	5	2021-02-07 17:47:23.944058+00	test	\N	\N	hostedimages-cdn	hostedimages-cdn	\N	\N	{Staging,Production}	\N	\N	\N
693	2	5	2021-02-07 17:47:24.032075+00	test	\N	\N	image-admin	image-admin	\N	MDF	\N	Puppet	Jenkins	\N
694	2	5	2021-02-07 17:47:24.109166+00	test	\N	\N	image-gallery	image-gallery	\N	MDF	{Testing,Staging,Production}	Puppet	Jenkins	\N
695	2	5	2021-02-07 17:47:24.191371+00	test	\N	\N	landing-pages	landing-pages	\N	MDF	{Testing,Staging,Production}	Puppet	Jenkins	\N
697	2	5	2021-02-07 17:47:24.423001+00	test	\N	\N	message-editor	message-editor	\N	MDF	{Testing,Staging,Production}	Puppet	Jenkins	\N
699	2	5	2021-02-07 17:47:24.638809+00	test	\N	\N	web-forms	web-forms	\N	MDF	{Staging,Production}	Puppet	Jenkins	\N
700	2	5	2021-02-07 17:47:24.71424+00	test	\N	\N	web-push-notifications	web-push-notifications	\N	MDF	{Testing,Staging,Production}	Puppet	Jenkins	\N
723	2	3	2021-02-07 17:47:26.607669+00	test	\N	\N	Campaign Sharing Consumers	campaign-sharing-consumers	\N	MDF	{Testing,Staging,Production}	Consul	Helm	Kubernetes
726	2	3	2021-02-07 17:47:26.980312+00	test	\N	\N	Rules Engine Campaign State	rules-engine-campaign-state	\N	MDF	{Testing,Staging,Production}	Consul	Helm	Kubernetes
727	2	3	2021-02-07 17:47:27.120374+00	test	\N	\N	Web Content Consumers	web-content-consumers	\N	MDF	{Testing,Staging,Production}	Consul	Helm	Kubernetes
728	2	3	2021-02-07 17:47:27.285322+00	test	\N	\N	Webforms CDN Consumer	webforms-cdn	\N	MDF	{Staging,Production}	Chef	Jenkins	\N
729	2	8	2021-02-07 17:47:27.359462+00	test	\N	\N	broadcast-archive-varnish	broadcast-archive-varnish	\N	MDF	{Testing,Staging,Production}	Consul	Helm	Kubernetes
730	2	8	2021-02-07 17:47:27.431854+00	test	\N	\N	cc-statsd	cc-statsd	\N	MDF	{Testing,Staging,Production}	Consul	Helm	Kubernetes
731	2	8	2021-02-07 17:47:27.50644+00	test	\N	\N	imageproxy-varnish	imageproxy-varnish	\N	MDF	{Testing,Staging,Production}	Consul	Helm	Kubernetes
732	3	5	2021-02-07 17:47:27.577371+00	test	\N	\N	Account Updates Client	account-updates-client	\N	MDF	{Staging,Production}	Consul	Helm	Kubernetes
733	3	5	2021-02-07 17:47:27.651206+00	test	\N	\N	Bulk Action History	bulk-action-history	\N	MDF	{Staging,Production}	Consul	Helm	Kubernetes
734	3	5	2021-02-07 17:47:27.721028+00	test	\N	\N	coi-message-editor	coi-message-editor	\N	MDF	{Staging,Production}	Consul	Helm	Kubernetes
735	3	8	2021-02-07 17:47:27.802306+00	test	\N	\N	f5-node-manager	f5-node-manager	\N	\N	{Staging,Production}	\N	\N	\N
736	3	5	2021-02-07 17:47:27.877025+00	test	\N	\N	Reports Client	reports-client	\N	MDF	{Staging,Production}	Consul	Helm	Kubernetes
737	3	5	2021-02-07 17:47:27.94707+00	test	\N	\N	Sites	sites	\N	MDF	{Staging,Production}	Consul	Helm	Kubernetes
738	3	1	2021-02-07 17:47:28.081545+00	test	\N	\N	Sites	sites	\N	MDF	{Staging,Production}	Consul	Helm	Kubernetes
739	3	5	2021-02-07 17:47:28.225375+00	test	\N	\N	Subscriber Import	subscriber-import	\N	MDF	{Staging,Production}	Consul	Helm	Kubernetes
745	3	5	2021-02-07 17:47:28.727318+00	test	\N	\N	user-profile-client	user-profile-client	\N	MDF	{Staging,Production}	Consul	Helm	Kubernetes
750	3	3	2021-02-07 17:47:29.15947+00	test	\N	\N	coiconsumer	coiconsumer	\N	MDF	{Testing,Staging,Production}	Consul	Helm	Kubernetes
751	3	3	2021-02-07 17:47:29.29842+00	test	\N	\N	core-consumers	core-consumers	\N	MDF	{Staging,Production}	Chef	Jenkins	\N
752	3	3	2021-02-07 17:47:29.368783+00	test	\N	\N	newsubnotifier	newsubnotifier	\N	MDF	{Staging,Production}	Consul	Helm	Kubernetes
753	3	3	2021-02-07 17:47:29.504978+00	test	\N	\N	subscriber-import-evaluation	subscriber-import-evaluation	\N	MDF	{Staging,Production}	Consul	Helm	Kubernetes
754	3	3	2021-02-07 17:47:29.634919+00	test	\N	\N	subscriber-import-processor	subscriber-import-processor	\N	MDF	{Staging,Production}	Consul	Helm	Kubernetes
755	3	3	2021-02-07 17:47:29.768719+00	test	\N	\N	subscriber-rebuild	subscriber-rebuild	\N	MDF	{Staging,Production}	Consul	Helm	Kubernetes
640	2	1	2021-02-07 17:47:18.115539+00	test	\N	\N	Campaign Proxy	campaign-proxy	\N	MDF	{Testing,Staging,Production}	Consul	Helm	Kubernetes
641	2	1	2021-02-07 17:47:18.267393+00	test	\N	\N	Checkpoint	checkpoint	\N	us-east-1	{Testing,Staging,Production}	SSM Parameter Store	ECS Pipeline Deploy	ECS
642	2	1	2021-02-07 17:47:18.451351+00	test	\N	\N	Content Hosting	content-hosting-service	\N	MDF	{Staging,Production}	Puppet	Jenkins	\N
643	2	1	2021-02-07 17:47:18.541892+00	test	\N	\N	Custom Domain	custom-domain	\N	MDF	{Testing,Staging,Production}	Consul	Helm	Kubernetes
646	2	1	2021-02-07 17:47:18.99486+00	test	\N	\N	Feed Proxy	feedproxy	\N	us-east-1	{Testing,Staging,Production}	SSM Parameter Store	ECS Pipeline Deploy	ECS (1st Gen)
647	2	8	2021-02-07 17:47:19.155228+00	test	\N	\N	HTTP Proxy	http-proxy	\N	us-east-1	{Testing,Staging,Production}	SSM Parameter Store	ECS Pipeline Deploy	ECS (1st Gen)
652	2	1	2021-02-07 17:47:19.817855+00	test	\N	\N	Message Map	messagemap	\N	us-east-1	{Testing,Staging,Production}	SSM Parameter Store	ECS Pipeline Deploy	ECS
653	2	1	2021-02-07 17:47:19.977395+00	test	\N	\N	Reimagine	reimagine	\N	MDF	{Staging,Production}	Chef	Jenkins	\N
655	2	1	2021-02-07 17:47:20.33822+00	test	\N	\N	Scheduler	scheduler	\N	MDF	{Testing,Staging,Production}	Consul	Helm	Kubernetes
657	2	8	2021-02-07 17:47:20.643866+00	test	\N	\N	Scheduler Publisher Redis	scheduler-publisher-redis	\N	MDF	{Testing,Staging,Production}	Consul	Helm	Kubernetes
658	2	1	2021-02-07 17:47:20.714896+00	test	\N	\N	Session Gateway	session-gateway	\N	MDF	{Staging,Production}	Chef	Jenkins	\N
659	2	8	2021-02-07 17:47:20.805506+00	test	\N	\N	Spam Analyze	spam-analyze	\N	MDF	{Testing,Staging,Production}	Consul	Helm	Kubernetes
660	2	1	2021-02-07 17:47:20.887814+00	test	\N	\N	Split Test	split-test	\N	MDF	{Testing,Staging,Production}	Consul	Helm	Kubernetes
661	2	1	2021-02-07 17:47:21.052533+00	test	\N	\N	Template Directory	template-directory	\N	MDF	{Staging,Production}	Consul	Helm	Kubernetes
662	2	1	2021-02-07 17:47:21.204206+00	test	\N	\N	Web Content	web-content	\N	MDF	{Testing,Staging,Production}	Consul	Helm	Kubernetes
664	2	8	2021-02-07 17:47:21.514154+00	test	\N	\N	Web Content Redis	web-content-redis	\N	MDF	{Testing,Staging,Production}	Consul	Helm	Kubernetes
665	2	8	2021-02-07 17:47:21.593524+00	test	\N	\N	Web Form Worker	web-form-worker	\N	MDF	{Staging,Production}	Chef	Jenkins	\N
666	2	1	2021-02-07 17:47:21.673499+00	test	\N	\N	Webfeed	webfeed	\N	MDF	{Testing,Staging,Production}	Consul	Helm	Kubernetes
667	2	4	2021-02-07 17:47:21.8399+00	test	\N	\N	analytics-broker	analytics-broker	\N	\N	\N	\N	\N	\N
668	2	4	2021-02-07 17:47:21.911774+00	test	\N	\N	analytics-models	analytics-models	\N	\N	\N	\N	\N	\N
669	2	4	2021-02-07 17:47:21.978728+00	test	\N	\N	aw-daemon	aw-daemon	\N	\N	\N	\N	\N	\N
670	2	4	2021-02-07 17:47:22.075476+00	test	\N	\N	AWBroadcasts	awbroadcasts	\N	\N	\N	\N	\N	\N
671	2	4	2021-02-07 17:47:22.159269+00	test	\N	\N	configuratron	configuratron	\N	\N	\N	\N	\N	\N
672	2	4	2021-02-07 17:47:22.239209+00	test	\N	\N	Deprecated Core Models	deprecated-core-models	\N	\N	\N	\N	\N	\N
673	2	4	2021-02-07 17:47:22.32105+00	test	\N	\N	Fetchable Feed	fetchable-feed	\N	\N	\N	\N	\N	\N
674	2	4	2021-02-07 17:47:22.391618+00	test	\N	\N	flaskapi	flaskapi	\N	\N	\N	\N	\N	\N
675	2	4	2021-02-07 17:47:22.466133+00	test	\N	\N	flaskapi-scalymongo	flaskapi-scalymongo	\N	\N	\N	\N	\N	\N
676	2	4	2021-02-07 17:47:22.538939+00	test	\N	\N	json-document	json-document	\N	\N	\N	\N	\N	\N
677	2	4	2021-02-07 17:47:22.613263+00	test	\N	\N	munge	munge	\N	\N	\N	\N	\N	\N
678	2	4	2021-02-07 17:47:22.689953+00	test	\N	\N	PikaChewie	PikaChewie	\N	\N	\N	\N	\N	\N
679	2	4	2021-02-07 17:47:22.766423+00	test	\N	\N	redcache	redcache	\N	\N	\N	\N	\N	\N
680	2	4	2021-02-07 17:47:22.850306+00	test	\N	\N	riak-facade	riak-facade	\N	\N	\N	\N	\N	\N
681	2	4	2021-02-07 17:47:22.927988+00	test	\N	\N	Rules Engine	rulesengine	\N	\N	\N	\N	\N	\N
682	2	4	2021-02-07 17:47:23.008458+00	test	\N	\N	Ruleset	ruleset	\N	\N	\N	\N	\N	\N
683	2	8	2021-02-07 17:47:23.087636+00	test	\N	\N	Ruleset Json Schema	ruleset-json-schema	\N	\N	\N	\N	\N	\N
684	2	4	2021-02-07 17:47:23.164449+00	test	\N	\N	Sprockets Mixins Service	sprockets-mixins-service	\N	\N	\N	\N	\N	\N
685	2	4	2021-02-07 17:47:23.236258+00	test	\N	\N	Sprockets Mixins Session	sprockets-mixins-session	\N	\N	\N	\N	\N	\N
686	2	4	2021-02-07 17:47:23.322409+00	test	\N	\N	Webform Models	webform-models	\N	\N	\N	\N	\N	\N
687	2	4	2021-02-07 17:47:23.401319+00	test	\N	\N	Zcode	zcode	\N	\N	\N	\N	\N	\N
688	2	5	2021-02-07 17:47:23.478221+00	test	\N	\N	broadcasts	broadcasts	\N	MDF	{Testing,Staging,Production}	Puppet	Jenkins	\N
690	2	5	2021-02-07 17:47:23.713341+00	test	\N	\N	customer-theme-manager	customer-theme-manager	\N	MDF	{Testing,Staging,Production}	Puppet	Jenkins	\N
691	2	5	2021-02-07 17:47:23.808946+00	test	\N	\N	draft-bin	draft-bin	\N	MDF	{Testing,Staging,Production}	Puppet	Jenkins	\N
696	2	5	2021-02-07 17:47:24.308342+00	test	\N	\N	landingpage-editor	landingpage-editor	\N	MDF	{Testing,Staging,Production}	Puppet	Jenkins	\N
698	2	5	2021-02-07 17:47:24.531054+00	test	\N	\N	message-statistics-js	message-statistics-js	\N	MDF	{Testing,Staging,Production}	Puppet	Jenkins	\N
701	2	5	2021-02-07 17:47:24.841953+00	test	\N	\N	webform-generator	webform-generator	\N	MDF	{Testing,Staging,Production}	Puppet	Jenkins	\N
702	2	4	2021-02-07 17:47:24.923633+00	test	\N	\N	aw-format-rate	aw-format-rate	\N	\N	\N	\N	\N	\N
703	2	4	2021-02-07 17:47:24.990996+00	test	\N	\N	aw-message-preview-util	aw-message-preview-util	\N	\N	\N	\N	\N	\N
704	2	4	2021-02-07 17:47:25.054446+00	test	\N	\N	aw-proxy-insecure-urls	aw-proxy-insecure-urls	\N	\N	\N	\N	\N	\N
705	2	4	2021-02-07 17:47:25.123189+00	test	\N	\N	awobfuscate-js	awobfuscate-js	\N	\N	\N	\N	\N	\N
706	2	4	2021-02-07 17:47:25.197085+00	test	\N	\N	backbone-editable-field	backbone-editable-field	\N	\N	\N	\N	\N	\N
707	2	4	2021-02-07 17:47:25.270846+00	test	\N	\N	backbone-paginator-view	backbone-paginator-view	\N	\N	\N	\N	\N	\N
708	2	4	2021-02-07 17:47:25.34523+00	test	\N	\N	backbone-send-window	backbone-send-window	\N	\N	\N	\N	\N	\N
709	2	4	2021-02-07 17:47:25.430473+00	test	\N	\N	beetl	beetl	\N	\N	\N	\N	\N	\N
710	2	4	2021-02-07 17:47:25.512719+00	test	\N	\N	beetl-lint	beetl-lint	\N	\N	\N	\N	\N	\N
711	2	4	2021-02-07 17:47:25.593103+00	test	\N	\N	Campaign Messages	campaign-messages	\N	\N	\N	\N	\N	\N
712	2	4	2021-02-07 17:47:25.676118+00	test	\N	\N	content-editor	content-editor	\N	\N	\N	\N	\N	\N
713	2	4	2021-02-07 17:47:25.765235+00	test	\N	\N	content-editor-landing-pages	content-editor-landing-pages	\N	\N	\N	\N	\N	\N
714	2	4	2021-02-07 17:47:25.842061+00	test	\N	\N	Landing Page JavaScript	landing-page-javascript	\N	\N	\N	\N	\N	\N
715	2	4	2021-02-07 17:47:25.913726+00	test	\N	\N	landing-page-templates	landing-page-templates	\N	\N	\N	\N	\N	\N
716	2	4	2021-02-07 17:47:25.987094+00	test	\N	\N	ruleset-helpers	ruleset-helpers	\N	\N	\N	\N	\N	\N
717	2	4	2021-02-07 17:47:26.05861+00	test	\N	\N	web-push-permission-prompt-templates	web-push-permission-prompt-templates	\N	\N	\N	\N	\N	\N
718	2	2	2021-02-07 17:47:26.138179+00	test	\N	\N	certificate-management	certificate-management	\N	\N	\N	\N	\N	\N
719	2	2	2021-02-07 17:47:26.207116+00	test	\N	\N	scheduler-event-auditor	scheduler-event-auditor	\N	\N	\N	\N	\N	\N
720	2	2	2021-02-07 17:47:26.290106+00	test	\N	\N	feed-publisher	feed-publisher	\N	\N	\N	\N	\N	\N
721	2	3	2021-02-07 17:47:26.359142+00	test	\N	\N	Campaign Engine Consumers	campaign-engine-consumers	\N	MDF	{Testing,Staging,Production}	Consul	Helm	Kubernetes
722	2	3	2021-02-07 17:47:26.499308+00	test	\N	\N	Campaign Extend Consumer	campaign-extend-consumer	\N	MDF	{Testing,Staging,Production}	Consul	Helm	Kubernetes
724	2	3	2021-02-07 17:47:26.716776+00	test	\N	\N	Feed Consumer	feed-consumer	\N	MDF	{Testing,Staging,Production}	Consul	Helm	Kubernetes
725	2	3	2021-02-07 17:47:26.885482+00	test	\N	\N	Legacy Followups Campaign Consumer	legacy-followups-campaign	\N	MDF	{Testing,Staging,Production}	Consul	Helm	Kubernetes
740	3	5	2021-02-07 17:47:28.330056+00	test	\N	\N	tag-management-client	tag-management-client	\N	MDF	{Staging,Production}	Consul	Helm	Kubernetes
741	3	5	2021-02-07 17:47:28.399388+00	test	\N	\N	unsubscribe	unsubscribe	\N	MDF	{Staging,Production}	Consul	Helm	Kubernetes
742	3	1	2021-02-07 17:47:28.47479+00	test	\N	\N	unsubscribe	unsubscribe	\N	MDF	{Staging,Production}	Consul	Helm	Kubernetes
743	3	2	2021-02-07 17:47:28.550504+00	test	\N	\N	unsubscribe	unsubscribe	\N	MDF	{Staging,Production}	Consul	Helm	Kubernetes
744	3	5	2021-02-07 17:47:28.62073+00	test	\N	\N	user-management-client	user-management-client	\N	MDF	{Staging,Production}	Consul	Helm	Kubernetes
746	3	5	2021-02-07 17:47:28.838031+00	test	\N	\N	verify-optin	verify-optin	\N	MDF	{Staging,Production}	Consul	Helm	Kubernetes
747	3	1	2021-02-07 17:47:28.908014+00	test	\N	\N	verify-optin	verify-optin	\N	MDF	{Staging,Production}	Consul	Helm	Kubernetes
748	3	2	2021-02-07 17:47:28.979247+00	test	\N	\N	verify-optin	verify-optin	\N	MDF	{Staging,Production}	Consul	Helm	Kubernetes
749	3	3	2021-02-07 17:47:29.04961+00	test	\N	\N	bulk-tagging-consumer	bulk-tagging-consumer	\N	us-east-1	{Staging,Production}	SSM Parameter Store	ECS Pipeline Deploy	ECS (1st Gen)
756	3	3	2021-02-07 17:47:29.87936+00	test	\N	\N	subscriber-sync	subscriber-sync	\N	us-east-1	{Staging,Production}	SSM Parameter Store	ECS Pipeline Deploy	ECS (1st Gen)
757	3	3	2021-02-07 17:47:30.009883+00	test	\N	\N	subscriber-tag-sync	subscriber-tag-sync	\N	MDF	{Staging,Production}	Consul	Helm	Kubernetes
758	3	3	2021-02-07 17:47:30.154703+00	test	\N	\N	tagpublisher	tagpublisher	\N	MDF	{Testing,Staging,Production}	Consul	Helm	Kubernetes
760	3	4	2021-02-07 17:47:30.377015+00	test	\N	\N	apisuspenders	apisuspenders	\N	\N	{Staging,Production}	\N	\N	\N
761	3	1	2021-02-07 17:47:30.447065+00	test	\N	\N	awlists	awlists	\N	MDF	{Staging,Production}	Chef	Jenkins	\N
764	3	1	2021-02-07 17:47:30.815295+00	test	\N	\N	email-verification	email-verification	\N	MDF	{Testing,Staging,Production}	Consul	Helm	Kubernetes
765	3	1	2021-02-07 17:47:30.950476+00	test	\N	\N	enlightener	enlightener	\N	MDF	{Staging,Production}	Chef	Jenkins	\N
766	3	1	2021-02-07 17:47:31.024629+00	test	\N	\N	geoip	geoip	\N	us-east-1	{Staging,Production}	SSM Parameter Store	ECS Pipeline Deploy	ECS (1st Gen)
767	3	1	2021-02-07 17:47:31.173242+00	test	\N	\N	import_allocations	import_allocations	\N	MDF	{Testing,Staging,Production}	Consul	Helm	Kubernetes
768	3	8	2021-02-07 17:47:31.242165+00	test	\N	\N	mail-relay	mail-relay	\N	MDF	{Staging,Production}	Consul	Helm	Kubernetes
769	3	1	2021-02-07 17:47:31.320546+00	test	\N	\N	recipient	recipient	\N	us-east-1	{Staging,Production}	SSM Parameter Store	ECS Pipeline Deploy	ECS (1st Gen)
770	3	1	2021-02-07 17:47:31.455688+00	test	\N	\N	Suspected Submission Spam Service	s4	\N	MDF	{Staging,Production}	Chef	Jenkins	\N
780	3	1	2021-02-07 17:47:32.659239+00	test	\N	\N	User management service	user-management	\N	MDF	{Testing,Staging,Production}	Consul	Helm	Kubernetes
781	3	2	2021-02-07 17:47:32.803597+00	test	\N	\N	commissions-processor	commissions-processor	\N	MDF	{Staging,Production}	Consul	\N	Rundeck
786	9	5	2021-02-07 17:47:33.405393+00	test	\N	\N	Account Settings Client	account-settings-client	\N	\N	{Testing,Staging,Production}	\N	\N	\N
789	9	5	2021-02-07 17:47:33.764987+00	test	\N	\N	Automatic Template Creator	automatic-template-creator	\N	\N	{Testing,Staging,Production}	\N	\N	\N
790	9	1	2021-02-07 17:47:33.835446+00	test	\N	\N	AWAccounts	awaccounts	\N	MDF	{Testing,Staging,Production}	Chef	Jenkins	\N
803	9	1	2021-02-07 17:47:35.132391+00	test	\N	\N	Extraction	extraction	\N	MDF	{Testing,Staging,Production}	Consul	Helm	Kubernetes
805	9	3	2021-02-07 17:47:35.404315+00	test	\N	\N	Kissmetrics Consumers	kissmetrics consumers	\N	us-east-1	{Testing,Staging,Production}	SSM Parameter Store	ECS Pipeline Deploy	ECS (1st Gen)
806	9	4	2021-02-07 17:47:35.54746+00	test	\N	\N	Kissmetrics Scripts	kissmetrics-scripts	\N	\N	{Staging,Production}	\N	\N	\N
807	9	5	2021-02-07 17:47:35.618221+00	test	\N	\N	List Automation Client	list-automation-client	\N	\N	{Staging,Production}	\N	\N	\N
813	9	3	2021-02-07 17:47:36.417656+00	test	\N	\N	Pageview Consumer	pageview-consumer	\N	MDF	{Testing,Staging,Production}	Consul	Helm	Kubernetes
816	9	3	2021-02-07 17:47:36.768066+00	test	\N	\N	Service Limits Dismisser	service-limits-dismisser	\N	MDF	{Testing,Staging,Production}	Consul	Helm	Kubernetes
818	9	3	2021-02-07 17:47:37.140359+00	test	\N	\N	Service Measurement Consumers	service-measurement-consumers	\N	MDF	{Testing,Staging,Production}	Consul	Helm	Kubernetes
819	9	3	2021-02-07 17:47:37.293106+00	test	\N	\N	Session Termination Consumer	session-termination-consumer	\N	MDF	{Testing,Staging,Production}	Consul	Helm	Kubernetes
821	9	1	2021-02-07 17:47:37.593095+00	test	\N	\N	Signup	signup	\N	MDF	{Testing,Staging,Production}	Consul	Helm	Kubernetes
823	9	2	2021-02-07 17:47:37.974083+00	test	\N	\N	Trial Account Processor	trial-account-processor	\N	MDF	{Staging,Production}	\N	\N	Rundeck
825	9	1	2021-02-07 17:47:38.236244+00	test	\N	\N	Webform Service	webform-service	\N	MDF	{Testing,Staging,Production}	Consul	Helm	Kubernetes
759	3	1	2021-02-07 17:47:30.270529+00	test	\N	\N	addleaduploader	addleaduploader	\N	MDF	{Staging,Production}	Chef	Jenkins	\N
762	3	1	2021-02-07 17:47:30.551065+00	test	\N	\N	awsubscribers	awsubscribers	\N	MDF	{Staging,Production}	Chef	Jenkins	\N
763	3	1	2021-02-07 17:47:30.687693+00	test	\N	\N	domain-validator	domain-validator	\N	MDF	{Staging,Production}	Chef	Jenkins	\N
771	3	1	2021-02-07 17:47:31.556222+00	test	\N	\N	search_recipients	search_recipients	\N	MDF	{Staging,Production}	Chef	Jenkins	\N
772	3	1	2021-02-07 17:47:31.623037+00	test	\N	\N	searchproxy	searchproxy	\N	MDF	{Staging,Production}	Chef	Jenkins	\N
773	3	1	2021-02-07 17:47:31.76838+00	test	\N	\N	Session Auth	session-auth	\N	MDF	{Testing,Staging,Production}	Consul	Helm	Kubernetes
774	3	1	2021-02-07 17:47:31.911174+00	test	\N	\N	subscriber-search	subscriber-search	\N	MDF	{Testing,Staging,Production}	Consul	Helm	Kubernetes
775	3	1	2021-02-07 17:47:32.046774+00	test	\N	\N	subscriberimportapi	subscriberimportapi	\N	MDF	{Testing,Staging,Production}	Consul	Helm	Kubernetes
776	3	1	2021-02-07 17:47:32.19322+00	test	\N	\N	subscriberproxy	subscriberproxy	\N	MDF	{Staging,Production}	Chef	Jenkins	\N
777	3	1	2021-02-07 17:47:32.319559+00	test	\N	\N	Tagging Service API	tagging	\N	us-east-1	{Staging,Production}	SSM Parameter Store	ECS Pipeline Deploy	ECS (1st Gen)
778	3	1	2021-02-07 17:47:32.445716+00	test	\N	\N	taggingproxy	taggingproxy	\N	MDF	{Staging,Production}	Chef	Jenkins	\N
779	3	1	2021-02-07 17:47:32.566874+00	test	\N	\N	verifications	verifications	\N	MDF	{Staging,Production}	Chef	Jenkins	\N
782	3	1	2021-02-07 17:47:32.912871+00	test	\N	\N	Mapping Service	mapping	\N	us-east-1	{Staging,Production}	SSM Parameter Store	ECS Pipeline Deploy	ECS (1st Gen)
783	3	1	2021-02-07 17:47:33.046901+00	test	\N	\N	bulk-tagging	bulk-tagging	\N	us-east-1	{Staging,Production}	SSM Parameter Store	ECS Pipeline Deploy	ECS (1st Gen)
784	3	1	2021-02-07 17:47:33.200328+00	test	\N	\N	Core-API	core-api	\N	MDF	{Staging,Production}	Chef	Jenkins	\N
785	3	1	2021-02-07 17:47:33.28368+00	test	\N	\N	segment-recipient	segment-recipient	\N	MDF	{Staging,Production}	Chef	Jenkins	\N
787	9	8	2021-02-07 17:47:33.517533+00	test	\N	\N	Affiliate Cookier	affiliate-cookier	\N	MDF	{Staging,Production}	Puppet	Jenkins	\N
788	9	3	2021-02-07 17:47:33.583221+00	test	\N	\N	Auto Webform Consumer	auto-webform-consumer	\N	MDF	{Testing,Staging,Production}	Consul	Helm	Kubernetes
791	9	2	2021-02-07 17:47:33.954361+00	test	\N	\N	Billing Processor	billing-processor	\N	MDF	{Staging,Production}	Ansible	Rundeck	\N
792	9	5	2021-02-07 17:47:34.106379+00	test	\N	\N	Cancellations	Cancellations	\N	MDF	{Staging,Production}	Chef	Jenkins	\N
793	9	1	2021-02-07 17:47:34.179267+00	test	\N	\N	Cancellations	Cancellations	\N	MDF	{Staging,Production}	Chef	Jenkins	\N
794	9	2	2021-02-07 17:47:34.238747+00	test	\N	\N	Credit Card Notification Publisher	cc-notification-publisher	\N	MDF	{Staging,Production}	Chef	Jenkins	\N
795	9	3	2021-02-07 17:47:34.307342+00	test	\N	\N	Credit Card Notifier	ccnotifier	\N	MDF	{Testing,Staging,Production}	Consul	Helm	Kubernetes
796	9	3	2021-02-07 17:47:34.367324+00	test	\N	\N	Commission Junction Consumer	commission-junction-consumer	\N	MDF	{Testing,Staging,Production}	Consul	Helm	Kubernetes
797	9	1	2021-02-07 17:47:34.487187+00	test	\N	\N	Commission Junction Service	commission-junction service	\N	MDF	{Testing,Staging,Production}	Consul	Helm	Kubernetes
798	9	4	2021-02-07 17:47:34.608235+00	test	\N	\N	Corporate Notifications	corporate-notifications	\N	\N	{Staging,Production}	\N	\N	\N
799	9	4	2021-02-07 17:47:34.671311+00	test	\N	\N	Credit Card Parse	credit-card-parse	\N	\N	{Staging,Production}	\N	\N	\N
800	9	1	2021-02-07 17:47:34.740397+00	test	\N	\N	Data Enrichment API	data-enrichment-api	\N	MDF	{Testing,Staging,Production}	Consul	Helm	Kubernetes
801	9	3	2021-02-07 17:47:34.890859+00	test	\N	\N	Data Enrichment Consumer	data-enrichment-consumer	\N	MDF	{Testing,Staging,Production}	Consul	Helm	Kubernetes
802	9	4	2021-02-07 17:47:35.024982+00	test	\N	\N	Deploy Client to S3	deploy-client-to-s3	\N	\N	{Testing,Staging,Production}	\N	\N	\N
804	9	8	2021-02-07 17:47:35.301928+00	test	\N	\N	Grafana Kissmetrics	grafana-kissmetrics	\N	\N	{Staging,Production}	\N	\N	\N
808	9	5	2021-02-07 17:47:35.722768+00	test	\N	\N	NUE	NUE	\N	MDF	{Staging,Production}	Chef	Jenkins	\N
809	9	1	2021-02-07 17:47:35.871273+00	test	\N	\N	NUE	NUE	\N	MDF	{Staging,Production}	Chef	Jenkins	\N
810	9	3	2021-02-07 17:47:36.014024+00	test	\N	\N	NUE Complete Tag Consumer	nue-complete-tag-consumer	\N	MDF	{Testing,Staging,Production}	Consul	Helm	Kubernetes
811	9	3	2021-02-07 17:47:36.160695+00	test	\N	\N	Onboarding Campaign Consumer	onboarding-campaign-consumer	\N	MDF	{Testing,Staging,Production}	Consul	Helm	Kubernetes
812	9	4	2021-02-07 17:47:36.308434+00	test	\N	\N	PayFlow Pro	payflowpro	\N	\N	{Staging,Production}	\N	\N	\N
814	9	2	2021-02-07 17:47:36.522997+00	test	\N	\N	Reset Password Email Metrics	reset-password-email-metrics	\N	MDF	{Testing,Staging,Production}	\N	\N	Rundeck
815	9	1	2021-02-07 17:47:36.596165+00	test	\N	\N	Service Limits	service-limits	\N	MDF	{Testing,Staging,Production}	Consul	Helm	Kubernetes
817	9	2	2021-02-07 17:47:36.957841+00	test	\N	\N	Service Limits Notifier	service-limits-notifier	\N	MDF	{Testing,Staging,Production}	\N	\N	Rundeck
820	9	1	2021-02-07 17:47:37.483255+00	test	\N	\N	Sessions	sessions	\N	MDF	{Staging,Production}	Chef	Jenkins	\N
822	9	1	2021-02-07 17:47:37.791872+00	test	\N	\N	Subdomain	subdomain	\N	MDF	{Testing,Staging,Production}	Consul	Helm	Kubernetes
824	9	8	2021-02-07 17:47:38.091194+00	test	\N	\N	Unauthenticated Kong	unauthenticated-kong	\N	MDF	{Testing,Staging,Production}	Consul	Helm	Kubernetes
829	4	3	2021-02-07 17:47:38.645185+00	test	\N	\N	autoresponse-worker	autoresponse-worker	\N	MDF	{Staging,Production}	Chef	Jenkins	\N
835	4	3	2021-02-07 17:47:39.545831+00	test	\N	\N	dr-results	dr-results	\N	MDF	{Testing,Staging,Production}	Chef	Jenkins	\N
836	4	3	2021-02-07 17:47:39.6862+00	test	\N	\N	dr-url-scraper	dr-url-scraper	\N	MDF	{Testing,Staging,Production}	Chef	Jenkins	\N
826	9	4	2021-02-07 17:47:38.389215+00	test	\N	\N	Webpage Spider	webpage-spider	\N	\N	{Staging,Production}	\N	\N	\N
827	9	2	2021-02-07 17:47:38.464002+00	test	\N	\N	Winback Promo Email	winback-promo-email	\N	\N	{Staging,Production}	\N	\N	\N
828	9	9	2021-02-07 17:47:38.536905+00	test	\N	\N	WWW	www	\N	MDF	{Staging,Production}	Chef	Jenkins	\N
830	4	3	2021-02-07 17:47:38.761028+00	test	\N	\N	broadcast-notification-scheduler	broadcast-notification-scheduler	\N	MDF	{Testing,Staging,Production}	Consul	Helm	Kubernetes
831	4	3	2021-02-07 17:47:38.905452+00	test	\N	\N	broadcast-notification-sender	broadcast-notification-sender	\N	MDF	{Testing,Staging,Production}	Consul	Helm	Kubernetes
832	4	3	2021-02-07 17:47:39.052565+00	test	\N	\N	Broadcaster	broadcaster	\N	MDF	{Testing,Staging,Production}	Consul	Helm	Kubernetes
833	4	3	2021-02-07 17:47:39.211786+00	test	\N	\N	composer	composer	\N	MDF	{Testing,Staging,Production}	Chef	Jenkins	\N
834	4	3	2021-02-07 17:47:39.367403+00	test	\N	\N	Deliverability Rollup Consumer	deliverability-rollup	\N	MDF	{Testing,Staging,Production}	Consul	Helm	Kubernetes
837	4	3	2021-02-07 17:47:39.879763+00	test	\N	\N	sift-url-publisher	sift-url-publisher	\N	MDF	{Testing,Staging,Production}	Chef	Jenkins	\N
839	4	3	2021-02-07 17:47:40.095971+00	test	\N	\N	hearsay	hearsay	\N	MDF	{Testing,Staging,Production}	Chef	Jenkins	\N
841	4	3	2021-02-07 17:47:40.329152+00	test	\N	\N	Sender Authentication Consumer	sender-authentication-consumer	\N	MDF	{Testing,Staging,Production}	Consul	Helm	Kubernetes
852	4	1	2021-02-07 17:47:41.799589+00	test	\N	\N	broadcast-starter	broadcast-starter	\N	MDF	{Testing,Staging,Production}	Consul	Helm	Kubernetes
853	4	1	2021-02-07 17:47:41.948985+00	test	\N	\N	Bulk Subscriber	bulk-subscriber	\N	MDF	{Testing,Staging,Production}	Consul	Helm	Kubernetes
854	4	1	2021-02-07 17:47:42.088547+00	test	\N	\N	clicktracking	clicktracking	\N	MDF	{Testing,Staging,Production}	Consul	Helm	Kubernetes
855	4	1	2021-02-07 17:47:42.235172+00	test	\N	\N	fixtureapi	fixtureapi	\N	\N	{Staging,Production}	\N	\N	\N
858	4	1	2021-02-07 17:47:42.59525+00	test	\N	\N	send-test	send-test	\N	MDF	{Testing,Staging,Production}	Consul	Helm	Kubernetes
859	4	1	2021-02-07 17:47:42.734461+00	test	\N	\N	Sender Authentication	sender-authentication	\N	MDF	{Testing,Staging,Production}	Consul	Helm	Kubernetes
860	4	1	2021-02-07 17:47:42.890155+00	test	\N	\N	Validation	validation	\N	MDF	{Testing,Staging,Production}	Consul	Helm	Kubernetes
868	4	2	2021-02-07 17:47:43.819281+00	test	\N	\N	momentum-configuration-generator	momentum-configuration-generator	\N	\N	{Staging,Production}	\N	\N	\N
870	4	2	2021-02-07 17:47:44.031788+00	test	\N	\N	reputation-mongo-cron	reputation-mongo-cron	\N	\N	\N	\N	\N	\N
871	4	2	2021-02-07 17:47:44.18014+00	test	\N	\N	reputation-rollups	reputation-rollups	\N	MDF	{Staging,Production}	Consul	Helm	Kubernetes
872	4	2	2021-02-07 17:47:44.258626+00	test	\N	\N	return-path-processor	return-path-processor	\N	\N	{Staging,Production}	\N	\N	\N
874	4	2	2021-02-07 17:47:44.467328+00	test	\N	\N	csleads_jira_report	csleads_jira_report	\N	MDF	\N	Chef	Jenkins	\N
875	4	2	2021-02-07 17:47:44.537061+00	test	\N	\N	passive_momentum_queue_check	passive_momentum_queue_check	\N	MDF	\N	Consul	Helm	Kubernetes
876	4	2	2021-02-07 17:47:44.605388+00	test	\N	\N	mailpoll	mailpoll	\N	MDF	{Testing,Staging,Production}	Consul	Helm	Kubernetes
902	4	4	2021-02-07 17:47:46.573741+00	test	\N	\N	librediscluster-perl	librediscluster-perl	\N	MDF	\N	Chef	Jenkins	\N
903	4	4	2021-02-07 17:47:46.639739+00	test	\N	\N	perl-JLogShovel	perl-JLogShovel	\N	MDF	\N	Ansible	Rundeck	\N
904	4	4	2021-02-07 17:47:46.702573+00	test	\N	\N	throttler	throttler	\N	\N	\N	\N	\N	\N
905	4	4	2021-02-07 17:47:46.782511+00	test	\N	\N	aw-mock	aw-mock	\N	MDF	\N	Chef	Jenkins	\N
906	4	4	2021-02-07 17:47:46.861735+00	test	\N	\N	libaw-statsd-perl	libaw-statsd-perl	\N	MDF	\N	Chef	Jenkins	\N
907	4	4	2021-02-07 17:47:46.931944+00	test	\N	\N	omnipitr	omnipitr	\N	MDF	\N	Chef	Jenkins	\N
908	4	4	2021-02-07 17:47:47.000144+00	test	\N	\N	aw-ehawk-talon	aw-ehawk-talon	\N	\N	\N	\N	\N	\N
909	4	8	2021-02-07 17:47:47.066027+00	test	\N	\N	statsd	statsd	\N	\N	{Staging,Production}	\N	\N	\N
910	4	8	2021-02-07 17:47:47.137107+00	test	\N	\N	corporate-mailer	corporate-mailer	\N	MDF	\N	Puppet	Jenkins	\N
911	4	8	2021-02-07 17:47:47.20603+00	test	\N	\N	ansible-playbooks	ansible-playbooks	\N	MDF	\N	Ansible	Rundeck	\N
912	4	8	2021-02-07 17:47:47.287142+00	test	\N	\N	aweber.momentum	aweber.momentum	\N	MDF	\N	Ansible	Rundeck	\N
913	4	8	2021-02-07 17:47:47.362572+00	test	\N	\N	edeliv-4947-momentum-svn-replacement-pilot	edeliv-4947-momentum-svn-replacement-pilot	\N	MDF	\N	Ansible	Rundeck	\N
914	4	8	2021-02-07 17:47:47.432812+00	test	\N	\N	rabbitmq-definitions	rabbitmq-definitions	\N	MDF	\N	Ansible	Rundeck	\N
915	4	8	2021-02-07 17:47:47.509905+00	test	\N	\N	rundeck-projects	rundeck-projects	\N	MDF	\N	Ansible	Rundeck	\N
916	4	8	2021-02-07 17:47:47.582165+00	test	\N	\N	production_classifier_notebook	production_classifier_notebook	\N	MDF	\N	Chef	Jenkins	\N
917	4	8	2021-02-07 17:47:47.653395+00	test	\N	\N	abusive-import-classifier	abusive-import-classifier	\N	MDF	\N	Chef	Jenkins	\N
918	4	8	2021-02-07 17:47:47.720398+00	test	\N	\N	alpine-python3-testing	alpine-python3-testing	\N	MDF	\N	Consul	Helm	Kubernetes
919	4	8	2021-02-07 17:47:47.800795+00	test	\N	\N	edeliv-perl-5-18-2	edeliv-perl-5-18-2	\N	MDF	\N	Ansible	Rundeck	\N
920	4	8	2021-02-07 17:47:47.876171+00	test	\N	\N	edeliv-python-test-2-6	edeliv-python-test-2-6	\N	\N	\N	\N	\N	\N
921	4	8	2021-02-07 17:47:47.943487+00	test	\N	\N	edeliv-python-test-2-7	edeliv-python-test-2-7	\N	\N	\N	\N	\N	\N
922	4	8	2021-02-07 17:47:48.013032+00	test	\N	\N	python-reputation-2.7	python-reputation-2.7	\N	MDF	\N	Consul	Helm	Kubernetes
923	4	8	2021-02-07 17:47:48.080326+00	test	\N	\N	edeliv-5595-identify-jinja-template	edeliv-5595-identify-jinja-template	\N	MDF	\N	Chef	Jenkins	\N
924	4	8	2021-02-07 17:47:48.153122+00	test	\N	\N	edeliv-6208-scheduler-audit	edeliv-6208-scheduler-audit	\N	MDF	\N	Chef	Jenkins	\N
925	4	8	2021-02-07 17:47:48.224865+00	test	\N	\N	awbin	awbin	\N	MDF	{Testing,Staging,Production}	Chef	Jenkins	\N
926	4	8	2021-02-07 17:47:48.3031+00	test	\N	\N	aweber-scripts	aweber-scripts	\N	MDF	{Testing,Staging,Production}	Chef	Jenkins	\N
927	4	8	2021-02-07 17:47:48.372878+00	test	\N	\N	aweber-support	aweber-support	\N	MDF	{Testing,Staging,Production}	Chef	Jenkins	\N
928	4	8	2021-02-07 17:47:48.449906+00	test	\N	\N	awlib	awlib	\N	MDF	{Testing,Staging,Production}	Chef	Jenkins	\N
929	4	8	2021-02-07 17:47:48.531849+00	test	\N	\N	awutil	awutil	\N	MDF	{Testing,Staging,Production}	Chef	Jenkins	\N
838	4	3	2021-02-07 17:47:39.98555+00	test	\N	\N	momentum-stats-consumers	momentum-stats-consumers	\N	MDF	{Testing,Staging,Production}	Consul	Helm	Kubernetes
840	4	3	2021-02-07 17:47:40.213533+00	test	\N	\N	reputation-workers	reputation-workers	\N	MDF	{Staging,Production}	Chef	Jenkins	\N
842	4	3	2021-02-07 17:47:40.432527+00	test	\N	\N	sift-message-content-publisher	sift-message-content-publisher	\N	MDF	{Testing,Staging,Production}	Consul	Helm	Kubernetes
843	4	3	2021-02-07 17:47:40.572971+00	test	\N	\N	spoolconsumer	spoolconsumer	\N	MDF	{Testing,Staging,Production}	Chef	Jenkins	\N
844	4	3	2021-02-07 17:47:40.720016+00	test	\N	\N	web-push-amplifier	web-push-amplifier	\N	MDF	{Testing,Staging,Production}	Consul	Helm	Kubernetes
845	4	3	2021-02-07 17:47:40.878748+00	test	\N	\N	web-push-sender	web-push-sender	\N	MDF	{Testing,Staging,Production}	Consul	Helm	Kubernetes
846	4	3	2021-02-07 17:47:41.020367+00	test	\N	\N	broadcast-notification-test	broadcast-notification-test	\N	\N	{Testing,Staging,Production}	\N	\N	\N
847	4	3	2021-02-07 17:47:41.092558+00	test	\N	\N	messagevalidator	messagevalidator	\N	MDF	{Testing,Staging,Production}	Consul	Helm	Kubernetes
848	4	5	2021-02-07 17:47:41.265295+00	test	\N	\N	reputation-ui	reputation-ui	\N	MDF	{Staging,Production}	Chef	Jenkins	\N
849	4	1	2021-02-07 17:47:41.340973+00	test	\N	\N	amp-broadcast	amp-broadcast	\N	MDF	{Testing,Staging,Production}	Consul	Helm	Kubernetes
850	4	1	2021-02-07 17:47:41.484116+00	test	\N	\N	Autohold	autohold	\N	MDF	{Testing,Staging,Production}	Consul	Helm	Kubernetes
851	4	1	2021-02-07 17:47:41.627295+00	test	\N	\N	Broadcast Segment	broadcast-segment	\N	MDF	{Testing,Staging,Production}	Consul	Helm	Kubernetes
856	4	1	2021-02-07 17:47:42.346449+00	test	\N	\N	reputation-api	reputation-api	\N	MDF	{Staging,Production}	Chef	Jenkins	\N
857	4	1	2021-02-07 17:47:42.418347+00	test	\N	\N	Routing	routing	\N	us-east-1	{Testing,Staging,Production}	SSM Parameter Store	ECS Pipeline Deploy	ECS (1st Gen)
861	4	1	2021-02-07 17:47:42.997382+00	test	\N	\N	web-push	web-push	\N	MDF	{Testing,Staging,Production}	Consul	Helm	Kubernetes
862	4	1	2021-02-07 17:47:43.141443+00	test	\N	\N	web-push-subscriber	web-push-subscriber	\N	MDF	{Testing,Staging,Production}	Consul	Helm	Kubernetes
863	4	1	2021-02-07 17:47:43.296507+00	test	\N	\N	web-push-view	web-push-view	\N	MDF	{Testing,Staging,Production}	Consul	Helm	Kubernetes
864	4	2	2021-02-07 17:47:43.434356+00	test	\N	\N	dr-poller	dr-poller	\N	MDF	{Testing,Staging,Production}	Consul	Helm	Kubernetes
865	4	2	2021-02-07 17:47:43.570854+00	test	\N	\N	links_analyzer	links_analyzer	\N	\N	{Testing,Staging,Production}	\N	\N	\N
866	4	2	2021-02-07 17:47:43.637677+00	test	\N	\N	phishtank-updater	phishtank-updater	\N	\N	\N	\N	\N	\N
867	4	2	2021-02-07 17:47:43.709506+00	test	\N	\N	google-postmaster-scraper	google-postmaster-scraper	\N	MDF	{Staging,Production}	Consul	Helm	Kubernetes
869	4	2	2021-02-07 17:47:43.928481+00	test	\N	\N	augur	augur	\N	MDF	{Staging,Production}	Chef	Jenkins	\N
873	4	2	2021-02-07 17:47:44.361833+00	test	\N	\N	snds-processor	snds-processor	\N	MDF	{Staging,Production}	Consul	Helm	Kubernetes
877	4	2	2021-02-07 17:47:44.708322+00	test	\N	\N	unsubscribe_blocked_email	unsubscribe_blocked_email	\N	\N	{Staging,Production}	\N	\N	\N
878	4	4	2021-02-07 17:47:44.788985+00	test	\N	\N	perl-avro	perl-avro	\N	\N	\N	\N	\N	\N
879	4	4	2021-02-07 17:47:44.861987+00	test	\N	\N	perl-jlog	perl-jlog	\N	\N	\N	\N	\N	\N
880	4	4	2021-02-07 17:47:44.929649+00	test	\N	\N	perl-net-amqp-rabbitmq	perl-net-amqp-rabbitmq	\N	\N	\N	\N	\N	\N
881	4	4	2021-02-07 17:47:45.000591+00	test	\N	\N	corporate-notifications	corporate-notifications	\N	MDF	\N	Puppet	Jenkins	\N
882	4	4	2021-02-07 17:47:45.069369+00	test	\N	\N	reputation-models	reputation-models	\N	MDF	\N	Chef	Jenkins	\N
883	4	4	2021-02-07 17:47:45.144211+00	test	\N	\N	aweber-content-render	aweber-content-render	\N	MDF	\N	Chef	Jenkins	\N
884	4	4	2021-02-07 17:47:45.216412+00	test	\N	\N	awfabfiles	awfabfiles	\N	MDF	\N	Chef	Jenkins	\N
885	4	4	2021-02-07 17:47:45.297182+00	test	\N	\N	base-event-worker	base-event-worker	\N	MDF	\N	Chef	Jenkins	\N
886	4	4	2021-02-07 17:47:45.375973+00	test	\N	\N	conditional-content-prototypes	conditional-content-prototypes	\N	MDF	\N	Chef	Jenkins	\N
887	4	4	2021-02-07 17:47:45.450311+00	test	\N	\N	connectionproxy	connectionproxy	\N	MDF	\N	Chef	Jenkins	\N
888	4	4	2021-02-07 17:47:45.521959+00	test	\N	\N	connectionproxy-rabbitmq	connectionproxy-rabbitmq	\N	MDF	\N	Chef	Jenkins	\N
889	4	4	2021-02-07 17:47:45.588565+00	test	\N	\N	ecsocket	ecsocket	\N	MDF	\N	Ansible	Rundeck	\N
890	4	4	2021-02-07 17:47:45.656573+00	test	\N	\N	email-validation	email-validation	\N	\N	\N	\N	\N	\N
891	4	4	2021-02-07 17:47:45.728938+00	test	\N	\N	geturl	geturl	\N	\N	\N	\N	\N	\N
892	4	4	2021-02-07 17:47:45.803843+00	test	\N	\N	heavymetl	heavymetl	\N	MDF	\N	Chef	Jenkins	\N
893	4	4	2021-02-07 17:47:45.881847+00	test	\N	\N	jwty	jwty	\N	\N	\N	\N	\N	\N
894	4	4	2021-02-07 17:47:45.949025+00	test	\N	\N	mailcontent	mailcontent	\N	\N	\N	\N	\N	\N
895	4	4	2021-02-07 17:47:46.01661+00	test	\N	\N	metl	metl	\N	MDF	\N	Chef	Jenkins	\N
896	4	4	2021-02-07 17:47:46.099423+00	test	\N	\N	mithril	mithril	\N	MDF	\N	Chef	Jenkins	\N
897	4	4	2021-02-07 17:47:46.169966+00	test	\N	\N	libcog-perl	libcog-perl	\N	MDF	\N	Chef	Jenkins	\N
898	4	4	2021-02-07 17:47:46.24038+00	test	\N	\N	libdistredis-perl	libdistredis-perl	\N	MDF	\N	Chef	Jenkins	\N
899	4	4	2021-02-07 17:47:46.32154+00	test	\N	\N	libhashring-perl	libhashring-perl	\N	MDF	\N	Chef	Jenkins	\N
900	4	4	2021-02-07 17:47:46.395475+00	test	\N	\N	libmemcached-libmemcached-perl	libmemcached-libmemcached-perl	\N	MDF	\N	Chef	Jenkins	\N
901	4	4	2021-02-07 17:47:46.468451+00	test	\N	\N	libredcache-perl	libredcache-perl	\N	MDF	\N	Chef	Jenkins	\N
931	4	8	2021-02-07 17:47:48.712511+00	test	\N	\N	Aweber Imbi	aweber-imbi	\N	MDF	{Staging,Production}	Ansible	Rundeck	\N
932	4	2	2021-02-07 17:47:48.794362+00	test	\N	\N	behave-automation	behave-automation	\N	MDF	{Staging,Production}	Ansible	Rundeck	\N
961	4	8	2021-02-07 17:47:50.97636+00	test	\N	\N	queue-diverted-bc	queue-diverted-bc	\N	MDF	{Staging,Production}	Chef	Jenkins	\N
966	5	1	2021-02-07 17:47:51.47737+00	test	\N	\N	AWeber Labs	aweber-labs	\N	MDF	{Testing,Staging,Production}	Consul	Helm	Kubernetes
967	5	9	2021-02-07 17:47:51.54833+00	test	\N	\N	AWeber Labs	aweber-labs	\N	MDF	{Testing,Staging,Production}	Consul	Helm	Kubernetes
968	5	2	2021-02-07 17:47:51.620293+00	test	\N	\N	Batch Sender	batch-sender	\N	MDF	\N	Consul	Helm	Kubernetes
970	5	2	2021-02-07 17:47:51.979216+00	test	\N	\N	Check Rate Limit	check-rate-limit	\N	MDF	\N	Consul	Helm	Kubernetes
930	4	8	2021-02-07 17:47:48.603475+00	test	\N	\N	perl-Momentum-JLogShovel	perl-Momentum-JLogShovel	\N	MDF	{Testing,Staging,Production}	Ansible	Rundeck	\N
933	4	8	2021-02-07 17:47:48.916842+00	test	\N	\N	behave-subscriber-cleanup	behave-subscriber-cleanup	\N	\N	{Staging,Production}	\N	\N	\N
934	4	2	2021-02-07 17:47:48.987358+00	test	\N	\N	broadcast-notification-test-poller	broadcast-notification-test-poller	\N	\N	{Testing,Staging,Production}	\N	\N	\N
935	4	8	2021-02-07 17:47:49.055142+00	test	\N	\N	conditional-content-test-data	conditional-content-test-data	\N	\N	{Testing,Staging,Production}	\N	\N	\N
936	4	9	2021-02-07 17:47:49.132259+00	test	\N	\N	k8-website-host	k8-website-host	\N	MDF	{Staging,Production}	Ansible	Rundeck	\N
937	4	2	2021-02-07 17:47:49.207056+00	test	\N	\N	routing-test	routing-test	\N	\N	{Staging,Production}	\N	\N	\N
938	4	2	2021-02-07 17:47:49.286983+00	test	\N	\N	trafficgenerator	trafficgenerator	\N	MDF	{Testing,Staging,Production}	Consul	Helm	Kubernetes
939	4	8	2021-02-07 17:47:49.355212+00	test	\N	\N	amp-kong	amp-kong	\N	MDF	{Testing,Staging,Production}	Consul	Helm	Kubernetes
940	4	8	2021-02-07 17:47:49.425216+00	test	\N	\N	edeliv-statsd	edeliv-statsd	\N	MDF	{Testing,Staging,Production}	Consul	Helm	Kubernetes
941	4	8	2021-02-07 17:47:49.496789+00	test	\N	\N	meapi-varnish	meapi-varnish	\N	MDF	{Staging,Production}	Consul	Helm	Kubernetes
942	4	8	2021-02-07 17:47:49.565652+00	test	\N	\N	minio	minio	\N	\N	\N	\N	\N	\N
943	4	8	2021-02-07 17:47:49.635882+00	test	\N	\N	mock-account-notes	mock-account-notes	\N	\N	\N	\N	\N	\N
944	4	8	2021-02-07 17:47:49.706062+00	test	\N	\N	mock-whoapi	mock-whoapi	\N	\N	\N	\N	\N	\N
945	4	8	2021-02-07 17:47:49.790622+00	test	\N	\N	splash	splash	\N	MDF	{Testing,Staging,Production}	Consul	Helm	Kubernetes
946	4	8	2021-02-07 17:47:49.864189+00	test	\N	\N	application-creation-utils	application-creation-utils	\N	\N	\N	\N	\N	\N
947	4	8	2021-02-07 17:47:49.936218+00	test	\N	\N	aws-docs-sync	aws-docs-sync	\N	us-east-1	\N	\N	GitLab CI	\N
948	4	8	2021-02-07 17:47:50.002487+00	test	\N	\N	consumer-util	consumer-util	\N	\N	\N	\N	\N	\N
949	4	8	2021-02-07 17:47:50.07232+00	test	\N	\N	db-scripts	db-scripts	\N	\N	\N	\N	\N	\N
950	4	8	2021-02-07 17:47:50.145181+00	test	\N	\N	dedicated-ip	dedicated-ip	\N	\N	\N	\N	\N	\N
951	4	8	2021-02-07 17:47:50.216836+00	test	\N	\N	Deliverability Utilities	deliverability-utilities	\N	\N	\N	\N	\N	\N
952	4	8	2021-02-07 17:47:50.294059+00	test	\N	\N	dr-utilities	dr-utilities	\N	\N	\N	\N	\N	\N
953	4	8	2021-02-07 17:47:50.363334+00	test	\N	\N	drdb-tools	drdb-tools	\N	\N	\N	\N	\N	\N
954	4	8	2021-02-07 17:47:50.431864+00	test	\N	\N	edeliv-utilities	edeliv-utilities	\N	\N	\N	\N	\N	\N
955	4	8	2021-02-07 17:47:50.504235+00	test	\N	\N	find-rewrite-accounts	find-rewrite-accounts	\N	MDF	{Staging,Production}	Consul	Helm	Kubernetes
956	4	8	2021-02-07 17:47:50.57207+00	test	\N	\N	graphite-metric-merging	graphite-metric-merging	\N	\N	\N	\N	\N	\N
957	4	8	2021-02-07 17:47:50.642244+00	test	\N	\N	jenkins-job-runner	jenkins-job-runner	\N	us-east-1	\N	\N	GitLab CI	\N
958	4	8	2021-02-07 17:47:50.712076+00	test	\N	\N	momentum-util	momentum-util	\N	\N	\N	\N	\N	\N
959	4	8	2021-02-07 17:47:50.791238+00	test	\N	\N	Nagios Check Status Report	nagios-check-status-report	\N	\N	\N	\N	\N	\N
960	4	8	2021-02-07 17:47:50.866876+00	test	\N	\N	perl-momentum-log-parsers	perl-momentum-log-parsers	\N	\N	{Testing,Staging,Production}	\N	\N	\N
962	4	8	2021-02-07 17:47:51.082597+00	test	\N	\N	rejected-node-assignments	rejected-node-assignments	\N	\N	{Staging,Production}	\N	\N	\N
963	4	8	2021-02-07 17:47:51.158453+00	test	\N	\N	smtp-echo-server	smtp-echo-server	\N	\N	{Staging,Production}	\N	\N	\N
964	5	1	2021-02-07 17:47:51.233197+00	test	\N	\N	AppStore Verifier	appstore-verifier	\N	MDF	{Testing,Staging,Production}	Consul	Helm	Kubernetes
965	5	1	2021-02-07 17:47:51.373035+00	test	\N	\N	AWeber Auth	aweber-auth	\N	MDF	{Staging,Production}	Puppet	Jenkins	\N
969	5	1	2021-02-07 17:47:51.800394+00	test	\N	\N	Callback Batching	callback-batching	\N	MDF	\N	Consul	Helm	Kubernetes
971	5	1	2021-02-07 17:47:52.076827+00	test	\N	\N	Core API: Followups	awfollowups	\N	MDF	{Staging,Production}	Chef	Jenkins	\N
972	5	4	2021-02-07 17:47:52.156305+00	test	\N	\N	Core Models	core-models	\N	\N	\N	\N	\N	\N
973	5	1	2021-02-07 17:47:52.229508+00	test	\N	\N	CP Auth	cp-auth	\N	MDF	{Staging,Production}	Consul	Helm	Kubernetes
977	5	4	2021-02-07 17:47:52.70635+00	test	\N	\N	GotoWebinar Common	gotowebinar-common	\N	\N	\N	\N	\N	\N
979	5	2	2021-02-07 17:47:53.003269+00	test	\N	\N	GotoWebinar Cron	gotowebinar-cron	\N	\N	{Staging,Production}	\N	\N	\N
980	5	5	2021-02-07 17:47:53.143609+00	test	\N	\N	Integrations Hub	integrations-hub	\N	\N	{Staging,Production}	\N	\N	\N
982	5	1	2021-02-07 17:47:53.365454+00	test	\N	\N	Integrations Service	integrations	\N	MDF	{Testing,Staging,Production}	Consul	Helm	Kubernetes
983	5	1	2021-02-07 17:47:53.503884+00	test	\N	\N	Labs Application	labs-application	\N	MDF	{Staging,Production}	Consul	Helm	Kubernetes
985	5	3	2021-02-07 17:47:53.779716+00	test	\N	\N	MobStatPush	mobstatpush	\N	MDF	{Testing,Staging,Production}	Consul	Helm	Kubernetes
986	5	1	2021-02-07 17:47:53.920851+00	test	\N	\N	OAuth 2 Revoke	oauth2revoke	\N	MDF	{Testing,Staging,Production}	Consul	Helm	Kubernetes
990	5	1	2021-02-07 17:47:54.490127+00	test	\N	\N	PAPI	papi	\N	MDF	{Testing,Staging,Production}	Consul	Helm	Kubernetes
992	5	1	2021-02-07 17:47:54.766675+00	test	\N	\N	PayPal IPN Service	paypal-ipn-service	\N	MDF	{Testing,Staging,Production}	Consul	Helm	Kubernetes
994	5	1	2021-02-07 17:47:55.055853+00	test	\N	\N	Public API: Account	publicapi-account	\N	\N	{Testing,Staging,Production}	\N	\N	\N
995	5	1	2021-02-07 17:47:55.20637+00	test	\N	\N	Public API: Broadcast	publicapi-broadcast	\N	MDF	{Testing,Staging,Production}	Consul	Helm	Kubernetes
997	5	1	2021-02-07 17:47:55.556099+00	test	\N	\N	Public API: Image	publicapi-image	\N	\N	{Testing,Staging,Production}	\N	\N	\N
998	5	1	2021-02-07 17:47:55.688612+00	test	\N	\N	Public API: Integration	publicapi-integration	\N	MDF	{Testing,Staging,Production}	Consul	Helm	Kubernetes
1000	5	1	2021-02-07 17:47:56.049435+00	test	\N	\N	Public API: List	publicapi-list	\N	MDF	{Testing,Staging,Production}	Consul	Helm	Kubernetes
1001	5	1	2021-02-07 17:47:56.193753+00	test	\N	\N	Public API: Webform	publicapi-webform	\N	MDF	{Testing,Staging,Production}	Consul	Helm	Kubernetes
1004	5	3	2021-02-07 17:47:56.606194+00	test	\N	\N	Push Notifier	pushnotifier	\N	MDF	{Testing,Staging,Production}	Consul	Helm	Kubernetes
974	5	1	2021-02-07 17:47:52.400518+00	test	\N	\N	Facebook Canvas	facebook-canvas	\N	MDF	{Staging,Production}	Puppet	Jenkins	\N
975	5	3	2021-02-07 17:47:52.470274+00	test	\N	\N	Facebook/Twitter Consumer	fbtwitter-consumer	\N	MDF	{Testing,Staging,Production}	Consul	Helm	Kubernetes
976	5	5	2021-02-07 17:47:52.606678+00	test	\N	\N	GotoWebinar Client	gotowebinar-client	\N	\N	{Staging,Production}	\N	\N	\N
978	5	3	2021-02-07 17:47:52.817734+00	test	\N	\N	GotoWebinar Consumers	gotowebinar-consumer	\N	MDF	{Testing,Staging,Production}	Consul	Helm	Kubernetes
981	5	5	2021-02-07 17:47:53.258414+00	test	\N	\N	Integrations Platform Client	integrations-platform-client	\N	\N	{Staging,Production}	\N	\N	\N
984	5	2	2021-02-07 17:47:53.670117+00	test	\N	\N	Labs Cleanup	labs-cleanup	\N	MDF	\N	Consul	Helm	Kubernetes
987	5	3	2021-02-07 17:47:54.10301+00	test	\N	\N	OAuth 2 User Revoker	oauth2-user-revoker	\N	MDF	\N	Consul	Helm	Kubernetes
988	5	4	2021-02-07 17:47:54.239647+00	test	\N	\N	OAuth MiddleWare	oauth-middleware	\N	\N	\N	\N	\N	\N
989	5	1	2021-02-07 17:47:54.319241+00	test	\N	\N	OAuth2 Login	oauth2login	\N	MDF	{Testing,Staging,Production}	Consul	Helm	Kubernetes
991	5	1	2021-02-07 17:47:54.664918+00	test	\N	\N	PayPal IPN Processor	paypal-ipn-processor	\N	MDF	{Testing,Staging,Production}	Consul	Helm	Kubernetes
993	5	1	2021-02-07 17:47:54.953269+00	test	\N	\N	Public API	public-api	\N	MDF	{Testing,Staging,Production}	Consul	Helm	Kubernetes
996	5	1	2021-02-07 17:47:55.386049+00	test	\N	\N	Public API: Custom Field	publicapi-custom-field	\N	MDF	{Testing,Staging,Production}	Consul	Helm	Kubernetes
999	5	1	2021-02-07 17:47:55.874352+00	test	\N	\N	Public API: Landing Page	publicapi-landing-page	\N	MDF	{Testing,Staging,Production}	Consul	Helm	Kubernetes
1002	5	4	2021-02-07 17:47:56.36521+00	test	\N	\N	PublicAPI Auth MIxin	publicapi-auth-mixin	\N	\N	\N	\N	\N	\N
1003	5	1	2021-02-07 17:47:56.435261+00	test	\N	\N	Push Config	pushconfig	\N	us-east-1	{Testing,Staging,Production}	SSM Parameter Store	ECS Pipeline Deploy	ECS
1005	5	4	2021-02-07 17:47:56.795811+00	test	\N	\N	Python Core Models	python-core-models	\N	\N	\N	\N	\N	\N
1006	5	4	2021-02-07 17:47:56.872555+00	test	\N	\N	Python JWT	python-jwt-lucid	\N	\N	\N	\N	\N	\N
1007	5	2	2021-02-07 17:47:56.945637+00	test	\N	\N	Shopify Checkout Poller	shopify-checkout-poller	\N	MDF	{Testing,Staging,Production}	Consul	Helm	Kubernetes
1008	5	1	2021-02-07 17:47:57.124236+00	test	\N	\N	Shopify Webhook Processor	shopify-webhook-processor	\N	MDF	{Testing,Staging,Production}	Consul	Helm	Kubernetes
1009	5	1	2021-02-07 17:47:57.30171+00	test	\N	\N	Subscriber Throttling	subscriber-throttling	\N	MDF	{Testing,Staging,Production}	Consul	Helm	Kubernetes
1010	5	2	2021-02-07 17:47:57.480107+00	test	\N	\N	Subscription Queue Processor	subscriptionqueueprocessor	\N	MDF	{Testing,Staging,Production}	Consul	Helm	Kubernetes
1011	5	1	2021-02-07 17:47:57.583833+00	test	\N	\N	Voyager	voyager	\N	MDF	{Testing,Staging,Production}	Consul	Helm	Kubernetes
1012	5	1	2021-02-07 17:47:57.764689+00	test	\N	\N	WASP	webhooks-add-subscriber-processor	\N	MDF	{Testing,Staging,Production}	Consul	Helm	Kubernetes
1013	5	2	2021-02-07 17:47:57.873034+00	test	\N	\N	WASP	webhooks-add-subscriber-processor	\N	MDF	{Testing,Staging,Production}	Consul	Helm	Kubernetes
1014	5	3	2021-02-07 17:47:57.975462+00	test	\N	\N	Webhooks Listener	webhooks-listener	\N	MDF	{Testing,Staging,Production}	Consul	Helm	Kubernetes
1015	5	3	2021-02-07 17:47:58.152433+00	test	\N	\N	Webhooks Sender	webhooks-sender	\N	MDF	{Testing,Staging,Production}	Consul	Helm	Kubernetes
1016	5	1	2021-02-07 17:47:58.332053+00	test	\N	\N	Weebly App	weeblyapp	\N	MDF	{Testing,Staging,Production}	Consul	Helm	Kubernetes
1017	5	8	2021-02-07 17:47:58.432982+00	test	\N	\N	Weebly Element	weeblyelement	\N	\N	{Staging,Production}	\N	\N	\N
1018	5	8	2021-02-07 17:47:58.500031+00	test	\N	\N	Wordpress Webform Widget	wordpress-webform-widget	\N	\N	{Staging,Production}	\N	\N	\N
1019	5	1	2021-02-07 17:47:58.569292+00	test	\N	\N	Zendesk Widget	zendesk-widget	\N	MDF	{Staging,Production}	Puppet	Jenkins	\N
1020	10	4	2021-02-07 17:47:58.638453+00	test	\N	\N	aweberjs	aweberjs	\N	\N	{Testing,Staging,Production}	\N	\N	\N
1021	6	1	2021-02-07 17:47:58.706533+00	test	\N	\N	Analytics Broker	anabroker	\N	us-east-1	{Testing,Staging,Production}	SSM Parameter Store	ECS Pipeline Deploy	ECS
1022	6	3	2021-02-07 17:47:58.89522+00	test	\N	\N	Analytics Consumers	anadb-consumers	\N	MDF	{Testing,Staging,Production}	Consul	Helm	Kubernetes
1023	6	8	2021-02-07 17:47:59.073352+00	test	\N	\N	Aircall Integration	aircall	\N	MDF	{Testing,Staging,Production}	Consul	Helm	Kubernetes
1024	6	8	2021-02-07 17:47:59.266181+00	test	\N	\N	Admin v1	admin	\N	MDF	{Testing,Staging,Production}	Consul	Helm	Kubernetes
1025	6	1	2021-02-07 17:47:59.40713+00	test	\N	\N	Admin v2	admin2	\N	MDF	{Staging,Production}	Consul	Helm	Kubernetes
1026	6	5	2021-02-07 17:47:59.476132+00	test	\N	\N	Admin v2	admin2	\N	MDF	{Staging,Production}	Consul	Helm	Kubernetes
1027	6	3	2021-02-07 17:47:59.545498+00	test	\N	\N	Phone Automation Scheduler	pa-scheduler	\N	MDF	{Testing,Staging,Production}	Consul	Helm	Kubernetes
1028	6	3	2021-02-07 17:47:59.686562+00	test	\N	\N	Phone Automation Dialer	pa-dialer	\N	MDF	{Testing,Staging,Production}	Consul	Helm	Kubernetes
1029	6	8	2021-02-07 17:47:59.832451+00	test	\N	\N	Phone Automation API	pa-api	\N	MDF	{Testing,Staging,Production}	Consul	Helm	Kubernetes
1030	6	3	2021-02-07 17:47:59.977355+00	test	\N	\N	Invoice Status Change Consumer	invoice-status-change-consumer	\N	MDF	{Testing,Staging,Production}	Consul	Helm	Kubernetes
1031	6	1	2021-02-07 17:48:00.122225+00	test	\N	\N	Imbi	imbi	\N	MDF	{Staging,Production}	Consul	Helm	Kubernetes
1032	6	5	2021-02-07 17:48:00.192426+00	test	\N	\N	Imbi	imbi	\N	MDF	{Staging,Production}	Consul	Helm	Kubernetes
1033	6	8	2021-02-07 17:48:00.263429+00	test	\N	\N	Zendesk Account Bot	zendesk-account-bot	\N	\N	{Staging,Production}	\N	\N	\N
1034	6	1	2021-02-07 17:48:00.333675+00	test	\N	\N	Analytics Ingestion	analytics-ingestion	\N	MDF	{Testing,Staging,Production}	Consul	Helm	Kubernetes
1035	6	8	2021-02-07 17:48:00.509622+00	test	\N	\N	Yodawg	yodawg	\N	MDF	{Staging,Production}	Consul	Helm	Kubernetes
1036	6	1	2021-02-07 17:48:00.577373+00	test	\N	\N	Rollup	rollup	\N	us-east-1	{Testing,Staging,Production}	SSM Parameter Store	ECS Pipeline Deploy	ECS
1039	6	3	2021-02-07 17:48:01.134798+00	test	\N	\N	FireHydrant Consumer	firehydrant	\N	MDF	{Testing,Staging,Production}	Consul	Helm	Kubernetes
1037	6	8	2021-02-07 17:48:00.765835+00	test	\N	\N	Rollup Distributor	rollup-distributor	\N	MDF	{Testing,Staging,Production}	Consul	Helm	Kubernetes
1038	6	3	2021-02-07 17:48:00.919974+00	test	\N	\N	Transmogrifier	transmogrifier	\N	MDF	{Testing,Staging,Production}	Consul	Helm	Kubernetes
\.


--
-- Data for Name: project_dependencies; Type: TABLE DATA; Schema: v1; Owner: postgres
--

COPY v1.project_dependencies (project_id, dependency_id, created_at, created_by) FROM stdin;
\.


--
-- Data for Name: project_fact_types; Type: TABLE DATA; Schema: v1; Owner: postgres
--

COPY v1.project_fact_types (id, created_at, created_by, last_modified_at, last_modified_by, project_type_id, fact_type, weight) FROM stdin;
1	2021-02-01 00:07:24.41556+00	test	2021-02-01 00:07:45.08432+00	test	1	Programming Language	30
2	2021-02-01 00:10:39.763978+00	test	\N	\N	1	Test Coverage	25
\.


--
-- Data for Name: project_fact_history; Type: TABLE DATA; Schema: v1; Owner: postgres
--

COPY v1.project_fact_history (project_id, fact_type_id, recorded_at, recorded_by, value, score, weight) FROM stdin;
\.


--
-- Data for Name: project_fact_type_options; Type: TABLE DATA; Schema: v1; Owner: postgres
--

COPY v1.project_fact_type_options (id, created_at, created_by, last_modified_at, last_modified_by, fact_type_id, value, score) FROM stdin;
\.


--
-- Data for Name: project_facts; Type: TABLE DATA; Schema: v1; Owner: postgres
--

COPY v1.project_facts (project_id, fact_type_id, created_at, created_by, last_modified_at, last_modified_by, value) FROM stdin;
\.


--
-- Data for Name: project_link_types; Type: TABLE DATA; Schema: v1; Owner: postgres
--

COPY v1.project_link_types (id, created_at, created_by, last_modified_at, last_modified_by, link_type, icon_class) FROM stdin;
1	2021-02-01 00:11:04.162806+00	test	\N	\N	GitLab Repository	fab gitlab
2	2021-02-01 00:11:31.827179+00	test	\N	\N	Grafana Dashboard	fas chart-line
3	2021-02-01 00:11:50.531043+00	test	2021-02-01 00:28:22.04299+00	test	Documentation	fas book
4	2021-02-01 00:14:46.283277+00	test	\N	\N	Sentry	imbi sentry
5	2021-02-03 20:31:18.299772+00	gavinr	\N	\N	SonarQube	imbi sonarqube
\.


--
-- Data for Name: project_links; Type: TABLE DATA; Schema: v1; Owner: postgres
--

COPY v1.project_links (project_id, link_type_id, created_at, created_by, last_modified_at, last_modified_by, url) FROM stdin;
1	1	2021-02-02 20:42:08.039404+00	gavinr	\N	\N	https://gitlab.aweber.io/PSE/Services/imbi
1	2	2021-02-02 20:42:08.811562+00	gavinr	\N	\N	https://grafana.aweber.io/d/000000296/home-dashboard?orgId=1
1	3	2021-02-02 20:42:10.531089+00	gavinr	\N	\N	https://imbi.readthedocs.org
1	4	2021-02-02 20:42:11.313994+00	gavinr	\N	\N	https://sentry.io/organizations/aweber-communications/issues/?project=5619880
636	1	2021-02-07 17:47:17.662098+00	test	\N	\N	https://gitlab.aweber.io/ASE/sync_zendesk_jira
637	1	2021-02-07 17:47:17.733238+00	test	\N	\N	https://gitlab.aweber.io/CC/Applications/broadcast-archive
638	2	2021-02-07 17:47:17.812624+00	test	\N	\N	https://grafana.aweber.io/d/000000514/broadcast-scheduling?orgId=1
638	4	2021-02-07 17:47:17.889035+00	test	\N	\N	https://sentry.io/organizations/aweber-communications/issues/?project=249097
639	2	2021-02-07 17:47:17.974637+00	test	\N	\N	https://grafana.aweber.io/d/000000279/campaign-service?orgId=1
639	4	2021-02-07 17:47:18.042353+00	test	\N	\N	https://sentry.io/settings/aweber-communications/projects/campaign-service/
640	1	2021-02-07 17:47:18.193423+00	test	\N	\N	https://gitlab.aweber.io/CC/Applications/campaign-proxy
641	1	2021-02-07 17:47:18.364978+00	test	\N	\N	https://gitlab.aweber.io/CC/Applications/checkpoint
643	1	2021-02-07 17:47:18.614356+00	test	\N	\N	https://gitlab.aweber.io/CC/Applications/custom-domain
643	5	2021-02-07 17:47:18.685044+00	test	\N	\N	https://sonarqube.aweber.io/dashboard?id=cc%3Acustom-domain
644	2	2021-02-07 17:47:18.765986+00	test	\N	\N	https://grafana.aweber.io/d/000000503/customer-exports?orgId=1
644	4	2021-02-07 17:47:18.843659+00	test	\N	\N	https://sentry.io/organizations/aweber-communications/issues/?project=241907
645	2	2021-02-07 17:47:18.919793+00	test	\N	\N	https://grafana.aweber.io/d/000000486/blog-broadcasts?orgId=1
646	1	2021-02-07 17:47:19.074229+00	test	\N	\N	https://gitlab.aweber.io/CC/Applications/feedproxy
647	1	2021-02-07 17:47:19.232964+00	test	\N	\N	https://gitlab.aweber.io/CC/Applications/http-proxy
648	1	2021-02-07 17:47:19.321099+00	test	\N	\N	https://gitlab.aweber.io/CC/Applications/imageproxy
649	2	2021-02-07 17:47:19.403408+00	test	\N	\N	https://grafana.aweber.io/d/mv3YS1iWk/message-service
649	4	2021-02-07 17:47:19.484446+00	test	\N	\N	https://sentry.io/organizations/aweber-communications/issues/?project=1423491
650	2	2021-02-07 17:47:19.562466+00	test	\N	\N	https://grafana.aweber.io/d/000000411/message-statistics-quickstats
650	4	2021-02-07 17:47:19.640729+00	test	\N	\N	https://sentry.io/organizations/aweber-communications/issues/?project=1767104
651	2	2021-02-07 17:47:19.720473+00	test	\N	\N	https://grafana.aweber.io/d/000000133/message-editor-api
652	1	2021-02-07 17:47:19.900883+00	test	\N	\N	https://gitlab.aweber.io/CC/Applications/messagemap
653	1	2021-02-07 17:47:20.066348+00	test	\N	\N	https://gitlab.aweber.io/CC/Applications/reimagine
654	2	2021-02-07 17:47:20.156133+00	test	\N	\N	https://grafana.aweber.io/d/000000252/rule-service?orgId=1&refresh=30s
654	4	2021-02-07 17:47:20.2574+00	test	\N	\N	https://sentry.io/organizations/aweber-communications/issues/?project=50686
655	1	2021-02-07 17:47:20.4177+00	test	\N	\N	https://gitlab.aweber.io/CC/Applications/scheduler
655	5	2021-02-07 17:47:20.493196+00	test	\N	\N	https://sonarqube.aweber.io/dashboard?id=cc%3Ascheduler
656	2	2021-02-07 17:47:20.569525+00	test	\N	\N	https://grafana.aweber.io/d/000000247/scheduler-service?orgId=1
660	1	2021-02-07 17:47:20.971031+00	test	\N	\N	https://gitlab.aweber.io/CC/Applications/split-test
661	4	2021-02-07 17:47:21.130714+00	test	\N	\N	https://sentry.io/organizations/aweber-communications/issues/?project=5372149
662	1	2021-02-07 17:47:21.291493+00	test	\N	\N	https://gitlab.aweber.io/CC/Applications/web-content
662	5	2021-02-07 17:47:21.370245+00	test	\N	\N	https://sonarqube.aweber.io/dashboard?id=cc%3Aweb-content
663	2	2021-02-07 17:47:21.442834+00	test	\N	\N	https://grafana.aweber.io/d/0_I-qnPWz/web-content-service?orgId=1
666	1	2021-02-07 17:47:21.760296+00	test	\N	\N	https://gitlab.aweber.io/CC/Applications/webfeed
688	4	2021-02-07 17:47:23.555296+00	test	\N	\N	https://sentry.io/organizations/aweber-communications/issues/?project=1284933
689	1	2021-02-07 17:47:23.635119+00	test	\N	\N	https://gitlab.aweber.io/CC/fe-applications/campaign-builder
691	4	2021-02-07 17:47:23.898159+00	test	\N	\N	https://sentry.io/organizations/aweber-communications/issues/?project=46827
692	1	2021-02-07 17:47:23.988209+00	test	\N	\N	https://gitlab.aweber.io/CC/fe-applications/hostedimages-cdn
693	1	2021-02-07 17:47:24.069114+00	test	\N	\N	https://gitlab.aweber.io/CC/fe-applications/image-admin
694	1	2021-02-07 17:47:24.155545+00	test	\N	\N	https://gitlab.aweber.io/CC/fe-applications/image-gallery
695	1	2021-02-07 17:47:24.229718+00	test	\N	\N	https://gitlab.aweber.io/CC/fe-applications/landing-pages
696	4	2021-02-07 17:47:24.384874+00	test	\N	\N	https://sentry.io/organizations/aweber-communications/issues/?project=2326975
697	1	2021-02-07 17:47:24.458397+00	test	\N	\N	https://gitlab.aweber.io/CC/fe-applications/message-editor
698	4	2021-02-07 17:47:24.602968+00	test	\N	\N	https://sentry.io/organizations/aweber-communications/issues/?project=1767104
699	1	2021-02-07 17:47:24.674336+00	test	\N	\N	https://gitlab.aweber.io/CC/fe-applications/web-forms
700	1	2021-02-07 17:47:24.762229+00	test	\N	\N	https://gitlab.aweber.io/CC/fe-applications/web-push-notifications
721	1	2021-02-07 17:47:26.42713+00	test	\N	\N	https://gitlab.aweber.io/CC/Consumers/campaign-engine-consumers
722	1	2021-02-07 17:47:26.571271+00	test	\N	\N	https://gitlab.aweber.io/CC/Consumers/campaign-extend-consumer
723	2	2021-02-07 17:47:26.648516+00	test	\N	\N	https://grafana.aweber.io/d/cEKonEIWk/campaign-proxy-dashboard?orgId=1
724	1	2021-02-07 17:47:26.808065+00	test	\N	\N	https://gitlab.aweber.io/CC/Consumers/feed-consumer
725	1	2021-02-07 17:47:26.95101+00	test	\N	\N	https://gitlab.aweber.io/CC/Consumers/legacy-followups-campaign
726	2	2021-02-07 17:47:27.013069+00	test	\N	\N	https://grafana.aweber.io/d/cEKonEIWk/campaign-proxy-dashboard?orgId=1
726	4	2021-02-07 17:47:27.084408+00	test	\N	\N	https://sentry.io/organizations/aweber-communications/issues/?project=103967
727	2	2021-02-07 17:47:27.16303+00	test	\N	\N	https://grafana.aweber.io/d/0_I-qnPWz/web-content-service?orgId=1
727	4	2021-02-07 17:47:27.242203+00	test	\N	\N	https://sentry.io/organizations/aweber-communications/issues/?project=2096863
728	1	2021-02-07 17:47:27.321409+00	test	\N	\N	https://gitlab.aweber.io/CC/Consumers/webforms-cdn
729	1	2021-02-07 17:47:27.395999+00	test	\N	\N	https://gitlab.aweber.io/CC/Services/broadcast-archive-varnish
730	1	2021-02-07 17:47:27.472727+00	test	\N	\N	https://gitlab.aweber.io/CC/Services/cc-statsd
731	1	2021-02-07 17:47:27.543677+00	test	\N	\N	https://gitlab.aweber.io/CC/Services/imageproxy-varnish
732	1	2021-02-07 17:47:27.61277+00	test	\N	\N	https://gitlab.aweber.io/CP/applications/account-updates-client
733	1	2021-02-07 17:47:27.686761+00	test	\N	\N	https://gitlab.aweber.io/CP/applications/bulk-action-history
734	1	2021-02-07 17:47:27.763112+00	test	\N	\N	https://gitlab.aweber.io/CP/applications/coi-message-editor
735	1	2021-02-07 17:47:27.842293+00	test	\N	\N	https://gitlab.aweber.io/CP/applications/f5-node-manager
736	1	2021-02-07 17:47:27.910768+00	test	\N	\N	https://gitlab.aweber.io/CP/applications/reports-client
737	2	2021-02-07 17:47:27.979085+00	test	\N	\N	https://grafana.aweber.io/d/000000530/account-logins
1024	1	2021-02-07 17:47:59.337059+00	test	\N	\N	https://gitlab.aweber.io/PSE/Applications/admin
638	1	2021-02-07 17:47:17.850028+00	test	\N	\N	https://gitlab.aweber.io/CC/Applications/broadcast-scheduling
639	1	2021-02-07 17:47:18.00862+00	test	\N	\N	https://gitlab.aweber.io/CC/Applications/campaign
639	5	2021-02-07 17:47:18.076489+00	test	\N	\N	https://sonarqube.aweber.io/dashboard?id=cc%3Acampaign
640	2	2021-02-07 17:47:18.154107+00	test	\N	\N	https://grafana.aweber.io/d/cEKonEIWk/campaign-proxy-dashboard
640	4	2021-02-07 17:47:18.226821+00	test	\N	\N	https://sentry.io/organizations/aweber-communications/issues/?project=54572
641	2	2021-02-07 17:47:18.31806+00	test	\N	\N	https://grafana.aweber.io/d/000000381/checkpoint-service?orgId=1&refresh=1m
641	4	2021-02-07 17:47:18.401433+00	test	\N	\N	https://sentry.io/settings/aweber-communications/projects/checkpoint-service/
642	1	2021-02-07 17:47:18.501773+00	test	\N	\N	https://gitlab.aweber.io/CC/Applications/content-hosting-service
643	2	2021-02-07 17:47:18.5783+00	test	\N	\N	https://grafana.aweber.io/d/-L2stkcMz/custom-domain-and-certificate-management?orgId=1
643	4	2021-02-07 17:47:18.647996+00	test	\N	\N	https://sentry.io/organizations/aweber-communications/issues/?project=5406730
644	1	2021-02-07 17:47:18.805153+00	test	\N	\N	https://gitlab.aweber.io/CC/Applications/customer-export
645	1	2021-02-07 17:47:18.958033+00	test	\N	\N	https://gitlab.aweber.io/CC/Applications/feed-processor
646	2	2021-02-07 17:47:19.035507+00	test	\N	\N	https://grafana.aweber.io/d/KqKobE2Zk/web-feed-system?orgId=1&refresh=1m
646	4	2021-02-07 17:47:19.116657+00	test	\N	\N	https://sentry.io/organizations/aweber-communications/issues/?project=222491
647	2	2021-02-07 17:47:19.195866+00	test	\N	\N	https://grafana.aweber.io/d/ykSFl_vmk/http-proxy?orgId=1
649	1	2021-02-07 17:47:19.441365+00	test	\N	\N	https://gitlab.aweber.io/CC/Applications/message
650	1	2021-02-07 17:47:19.601375+00	test	\N	\N	https://gitlab.aweber.io/CC/Applications/message-statistics
651	1	2021-02-07 17:47:19.770207+00	test	\N	\N	https://gitlab.aweber.io/CC/Applications/messageeditorapi
652	2	2021-02-07 17:47:19.861341+00	test	\N	\N	https://grafana.aweber.io/d/nzvbF-0ik/messagemap-service?orgId=1
652	4	2021-02-07 17:47:19.938357+00	test	\N	\N	https://sentry.io/organizations/aweber-communications/issues/?project=52228
653	2	2021-02-07 17:47:20.020043+00	test	\N	\N	https://grafana.aweber.io/d/000000012/image-hosting-backend?orgId=1
654	1	2021-02-07 17:47:20.202983+00	test	\N	\N	https://gitlab.aweber.io/CC/Applications/rule
654	5	2021-02-07 17:47:20.296058+00	test	\N	\N	https://sonarqube.aweber.io/dashboard?id=cc%3Arule
655	2	2021-02-07 17:47:20.378024+00	test	\N	\N	https://grafana.aweber.io/d/000000247/scheduler-service?orgId=1
655	4	2021-02-07 17:47:20.456767+00	test	\N	\N	https://sentry.io/organizations/aweber-communications/issues/?project=51068
656	1	2021-02-07 17:47:20.607462+00	test	\N	\N	https://gitlab.aweber.io/CC/Applications/scheduler-publisher
657	1	2021-02-07 17:47:20.67803+00	test	\N	\N	https://gitlab.aweber.io/CC/Applications/scheduler-publisher-redis
658	1	2021-02-07 17:47:20.7625+00	test	\N	\N	https://gitlab.aweber.io/CC/Applications/session-gateway
659	1	2021-02-07 17:47:20.848079+00	test	\N	\N	https://gitlab.aweber.io/CC/Applications/spam-analyze
660	2	2021-02-07 17:47:20.929721+00	test	\N	\N	https://grafana.aweber.io/d/8s7FsiNiz/split-test?orgId=1
660	4	2021-02-07 17:47:21.011763+00	test	\N	\N	https://sentry.io/organizations/aweber-communications/issues/?project=1204490
661	1	2021-02-07 17:47:21.093075+00	test	\N	\N	https://gitlab.aweber.io/CC/Applications/template-directory
661	5	2021-02-07 17:47:21.166668+00	test	\N	\N	https://sonarqube.aweber.io/dashboard?id=cc%3Atemplate-directory
662	2	2021-02-07 17:47:21.254815+00	test	\N	\N	https://grafana.aweber.io/d/0_I-qnPWz/web-content-service?orgId=1
662	4	2021-02-07 17:47:21.332763+00	test	\N	\N	https://sentry.io/organizations/aweber-communications/issues/?project=1869102
663	1	2021-02-07 17:47:21.476691+00	test	\N	\N	https://gitlab.aweber.io/CC/Applications/web-content-gateway
664	1	2021-02-07 17:47:21.554741+00	test	\N	\N	https://gitlab.aweber.io/CC/Applications/web-content-redis
665	1	2021-02-07 17:47:21.635477+00	test	\N	\N	https://gitlab.aweber.io/CC/Applications/web-form-worker
666	2	2021-02-07 17:47:21.711159+00	test	\N	\N	https://grafana.aweber.io/d/8oHfIIRZk/sendtest-webfeed-service?orgId=1
666	4	2021-02-07 17:47:21.80319+00	test	\N	\N	https://sentry.io/organizations/aweber-communications/issues/?project=1417920
667	1	2021-02-07 17:47:21.877535+00	test	\N	\N	https://gitlab.aweber.io/CC/Libraries/analytics-broker
668	1	2021-02-07 17:47:21.946935+00	test	\N	\N	https://gitlab.aweber.io/CC/Libraries/analytics-models
669	1	2021-02-07 17:47:22.030985+00	test	\N	\N	https://gitlab.aweber.io/CC/Libraries/aw-daemon
670	1	2021-02-07 17:47:22.120282+00	test	\N	\N	https://gitlab.aweber.io/CC/Libraries/awbroadcasts
671	1	2021-02-07 17:47:22.204703+00	test	\N	\N	https://gitlab.aweber.io/CC/Libraries/configuratron
672	1	2021-02-07 17:47:22.284235+00	test	\N	\N	https://gitlab.aweber.io/CC/Libraries/deprecated-core-models
673	1	2021-02-07 17:47:22.358134+00	test	\N	\N	https://gitlab.aweber.io/CC/Libraries/fetchable-feed
674	1	2021-02-07 17:47:22.431486+00	test	\N	\N	https://gitlab.aweber.io/CC/Libraries/flaskapi
675	1	2021-02-07 17:47:22.504881+00	test	\N	\N	https://gitlab.aweber.io/CC/Libraries/flaskapi-scalymongo
676	1	2021-02-07 17:47:22.574419+00	test	\N	\N	https://gitlab.aweber.io/CC/Libraries/json-document
677	1	2021-02-07 17:47:22.65137+00	test	\N	\N	https://gitlab.aweber.io/CC/Libraries/munge
678	1	2021-02-07 17:47:22.729978+00	test	\N	\N	https://gitlab.aweber.io/CC/Libraries/PikaChewie
679	1	2021-02-07 17:47:22.811651+00	test	\N	\N	https://gitlab.aweber.io/CC/Libraries/redcache
680	1	2021-02-07 17:47:22.888652+00	test	\N	\N	https://gitlab.aweber.io/CC/Libraries/riak-facade
681	1	2021-02-07 17:47:22.968007+00	test	\N	\N	https://gitlab.aweber.io/CC/Libraries/rulesengine
682	1	2021-02-07 17:47:23.049054+00	test	\N	\N	https://gitlab.aweber.io/CC/Libraries/ruleset
683	1	2021-02-07 17:47:23.12951+00	test	\N	\N	https://gitlab.aweber.io/CC/Libraries/ruleset-json-schema
684	1	2021-02-07 17:47:23.201032+00	test	\N	\N	https://gitlab.aweber.io/CC/Libraries/sprockets-mixins-service
685	1	2021-02-07 17:47:23.282115+00	test	\N	\N	https://gitlab.aweber.io/CC/Libraries/sprockets-mixins-session
686	1	2021-02-07 17:47:23.361891+00	test	\N	\N	https://gitlab.aweber.io/CC/Libraries/webform-models
687	1	2021-02-07 17:47:23.439099+00	test	\N	\N	https://gitlab.aweber.io/CC/Libraries/zcode
688	1	2021-02-07 17:47:23.51798+00	test	\N	\N	https://gitlab.aweber.io/CC/fe-applications/broadcasts
689	4	2021-02-07 17:47:23.673516+00	test	\N	\N	https://sentry.io/organizations/aweber-communications/issues/?project=54304
690	1	2021-02-07 17:47:23.760758+00	test	\N	\N	https://gitlab.aweber.io/CC/fe-applications/customer-theme-manager
691	1	2021-02-07 17:47:23.84899+00	test	\N	\N	https://gitlab.aweber.io/CC/fe-applications/draft-bin
695	4	2021-02-07 17:47:24.268785+00	test	\N	\N	https://sentry.io/organizations/aweber-communications/issues/?project=2326975
696	1	2021-02-07 17:47:24.346812+00	test	\N	\N	https://gitlab.aweber.io/CC/fe-applications/landingpage-editor
697	4	2021-02-07 17:47:24.493487+00	test	\N	\N	https://sentry.io/organizations/aweber-communications/issues/?project=61945
698	1	2021-02-07 17:47:24.567037+00	test	\N	\N	https://gitlab.aweber.io/CC/fe-applications/message-statistics-js
700	4	2021-02-07 17:47:24.801677+00	test	\N	\N	https://sentry.io/organizations/aweber-communications/issues/?project=5499260
701	1	2021-02-07 17:47:24.887077+00	test	\N	\N	https://gitlab.aweber.io/CC/fe-applications/webform-generator
702	1	2021-02-07 17:47:24.958967+00	test	\N	\N	https://gitlab.aweber.io/CC/fe-libraries/aw-format-rate
703	1	2021-02-07 17:47:25.021519+00	test	\N	\N	https://gitlab.aweber.io/CC/fe-libraries/aw-message-preview-util
704	1	2021-02-07 17:47:25.086141+00	test	\N	\N	https://gitlab.aweber.io/CC/fe-libraries/aw-proxy-insecure-urls
705	1	2021-02-07 17:47:25.163059+00	test	\N	\N	https://gitlab.aweber.io/CC/fe-libraries/awobfuscate-js
706	1	2021-02-07 17:47:25.234073+00	test	\N	\N	https://gitlab.aweber.io/CC/fe-libraries/backbone-editable-field
707	1	2021-02-07 17:47:25.307477+00	test	\N	\N	https://gitlab.aweber.io/CC/fe-libraries/backbone-paginator-view
708	1	2021-02-07 17:47:25.389422+00	test	\N	\N	https://gitlab.aweber.io/CC/fe-libraries/backbone-send-window
709	1	2021-02-07 17:47:25.472401+00	test	\N	\N	https://gitlab.aweber.io/CC/fe-libraries/beetl
710	1	2021-02-07 17:47:25.552237+00	test	\N	\N	https://gitlab.aweber.io/CC/fe-libraries/beetl-lint
711	1	2021-02-07 17:47:25.635797+00	test	\N	\N	https://gitlab.aweber.io/CC/fe-libraries/campaign-messages
712	1	2021-02-07 17:47:25.718539+00	test	\N	\N	https://gitlab.aweber.io/CC/fe-libraries/content-editor
713	1	2021-02-07 17:47:25.807258+00	test	\N	\N	https://gitlab.aweber.io/CC/fe-libraries/content-editor-landing-pages
714	1	2021-02-07 17:47:25.879069+00	test	\N	\N	https://gitlab.aweber.io/CC/fe-libraries/landing-page-javascript
715	1	2021-02-07 17:47:25.951091+00	test	\N	\N	https://gitlab.aweber.io/CC/fe-libraries/landing-page-templates
716	1	2021-02-07 17:47:26.022493+00	test	\N	\N	https://gitlab.aweber.io/CC/fe-libraries/ruleset-helpers
717	1	2021-02-07 17:47:26.098404+00	test	\N	\N	https://gitlab.aweber.io/CC/fe-libraries/web-push-permission-prompt-templates
718	1	2021-02-07 17:47:26.171445+00	test	\N	\N	https://gitlab.aweber.io/CC/rundeck/certificate-management
719	1	2021-02-07 17:47:26.254984+00	test	\N	\N	https://gitlab.aweber.io/CC/rundeck/scheduler-event-auditor
720	1	2021-02-07 17:47:26.323757+00	test	\N	\N	https://gitlab.aweber.io/CC/rundeck/feed-publisher
721	2	2021-02-07 17:47:26.394305+00	test	\N	\N	https://grafana.aweber.io/d/AsASNcfik/campaign-engine?orgId=1
721	4	2021-02-07 17:47:26.464839+00	test	\N	\N	https://sentry.io/organizations/aweber-communications/issues/?project=103967
722	2	2021-02-07 17:47:26.536996+00	test	\N	\N	https://grafana.aweber.io/d/NCkp0_zWk/campaign-extend?orgId=1
723	1	2021-02-07 17:47:26.68374+00	test	\N	\N	https://gitlab.aweber.io/CC/Consumers/campaign-sharing-consumers
724	2	2021-02-07 17:47:26.764275+00	test	\N	\N	https://grafana.aweber.io/d/KqKobE2Zk/web-feed-system?orgId=1&refresh=1m
724	4	2021-02-07 17:47:26.846237+00	test	\N	\N	https://sentry.io/organizations/aweber-communications/issues/?project=1417920
725	2	2021-02-07 17:47:26.918516+00	test	\N	\N	https://grafana.aweber.io/d/000000077/legacy-followups-campaign-consumer?orgId=1
726	1	2021-02-07 17:47:27.049298+00	test	\N	\N	https://gitlab.aweber.io/CC/Consumers/rules-engine-campaign-state
727	1	2021-02-07 17:47:27.199707+00	test	\N	\N	https://gitlab.aweber.io/CC/Consumers/web-content-consumers
737	1	2021-02-07 17:47:28.010971+00	test	\N	\N	https://gitlab.aweber.io/CP/applications/sites
738	1	2021-02-07 17:47:28.157071+00	test	\N	\N	https://gitlab.aweber.io/CP/applications/sites
739	4	2021-02-07 17:47:28.296678+00	test	\N	\N	https://sentry.io/organizations/aweber-communications/issues/?project=87677
740	1	2021-02-07 17:47:28.366458+00	test	\N	\N	https://gitlab.aweber.io/CP/applications/tag-management-client
741	1	2021-02-07 17:47:28.437216+00	test	\N	\N	https://gitlab.aweber.io/CP/applications/unsubscribe
742	1	2021-02-07 17:47:28.511023+00	test	\N	\N	https://gitlab.aweber.io/CP/applications/unsubscribe
743	1	2021-02-07 17:47:28.587025+00	test	\N	\N	https://gitlab.aweber.io/CP/applications/unsubscribe
744	1	2021-02-07 17:47:28.658023+00	test	\N	\N	https://gitlab.aweber.io/CP/applications/user-management-client
745	4	2021-02-07 17:47:28.797932+00	test	\N	\N	https://sentry.io/organizations/aweber-communications/issues/?project=1491235
746	1	2021-02-07 17:47:28.873954+00	test	\N	\N	https://gitlab.aweber.io/CP/applications/verify-optin
747	1	2021-02-07 17:47:28.945079+00	test	\N	\N	https://gitlab.aweber.io/CP/applications/verify-optin
748	1	2021-02-07 17:47:29.013829+00	test	\N	\N	https://gitlab.aweber.io/CP/applications/verify-optin
749	1	2021-02-07 17:47:29.08444+00	test	\N	\N	https://gitlab.aweber.io/CP/Consumers/bulk-tagging-consumer
750	1	2021-02-07 17:47:29.225671+00	test	\N	\N	https://gitlab.aweber.io/CP/Consumers/coiconsumer
752	1	2021-02-07 17:47:29.436771+00	test	\N	\N	https://gitlab.aweber.io/CP/Consumers/newsubnotifier
753	1	2021-02-07 17:47:29.570477+00	test	\N	\N	https://gitlab.aweber.io/CP/Consumers/subscriber-import-evaluation
754	1	2021-02-07 17:47:29.700297+00	test	\N	\N	https://gitlab.aweber.io/CP/Consumers/subscriber-import-processor
755	4	2021-02-07 17:47:29.844509+00	test	\N	\N	https://sentry.io/organizations/aweber-communications/issues/?project=147959
756	2	2021-02-07 17:47:29.911196+00	test	\N	\N	https://grafana.aweber.io/dashboard/db/subscriber-sync-consumers
756	4	2021-02-07 17:47:29.978891+00	test	\N	\N	https://sentry.io/organizations/aweber-communications/issues/?project=104527
757	2	2021-02-07 17:47:30.044502+00	test	\N	\N	https://grafana.aweber.io/d/000000241/tagging-service
757	4	2021-02-07 17:47:30.116856+00	test	\N	\N	https://sentry.io/organizations/aweber-communications/issues/?project=182372
758	2	2021-02-07 17:47:30.188815+00	test	\N	\N	https://grafana.aweber.io/d/000000248/tag-publisher
759	1	2021-02-07 17:47:30.343182+00	test	\N	\N	https://gitlab.aweber.io/CP/Services/addleaduploader
760	1	2021-02-07 17:47:30.410879+00	test	\N	\N	https://gitlab.aweber.io/CP/Services/apisuspenders
761	2	2021-02-07 17:47:30.480226+00	test	\N	\N	https://grafana.aweber.io/d/000000491/awlists-dashboard
762	1	2021-02-07 17:47:30.618852+00	test	\N	\N	https://gitlab.aweber.io/CP/Services/awsubscribers
763	1	2021-02-07 17:47:30.774167+00	test	\N	\N	https://gitlab.aweber.io/CP/Services/domain-validator
764	2	2021-02-07 17:47:30.849321+00	test	\N	\N	https://grafana.aweber.io/d/_wcHNmMWz/email-verification-service
764	4	2021-02-07 17:47:30.916893+00	test	\N	\N	https://sentry.io/organizations/aweber-communications/issues/?project=1469720
765	1	2021-02-07 17:47:30.98854+00	test	\N	\N	https://gitlab.aweber.io/CP/Services/enlightener
766	2	2021-02-07 17:47:31.061331+00	test	\N	\N	https://grafana.aweber.io/d/000000212/geoip-service
766	4	2021-02-07 17:47:31.137162+00	test	\N	\N	https://sentry.io/organizations/aweber-communications/issues/?project=53638
767	1	2021-02-07 17:47:31.208842+00	test	\N	\N	https://gitlab.aweber.io/CP/Services/import_allocations
768	1	2021-02-07 17:47:31.286471+00	test	\N	\N	https://gitlab.aweber.io/CP/Services/mail-relay
769	2	2021-02-07 17:47:31.354176+00	test	\N	\N	https://grafana.aweber.io/d/000000371/recipient-service
769	4	2021-02-07 17:47:31.423124+00	test	\N	\N	https://sentry.io/organizations/aweber-communications/issues/?project=44835
770	2	2021-02-07 17:47:31.492499+00	test	\N	\N	https://grafana.aweber.io/d/000000121/webform-spam-s4
772	1	2021-02-07 17:47:31.68966+00	test	\N	\N	https://gitlab.aweber.io/CP/Services/searchproxy
773	1	2021-02-07 17:47:31.840682+00	test	\N	\N	https://gitlab.aweber.io/CP/applications/session-auth
774	1	2021-02-07 17:47:31.979713+00	test	\N	\N	https://gitlab.aweber.io/CP/Services/subscriber-search
775	1	2021-02-07 17:47:32.119989+00	test	\N	\N	https://gitlab.aweber.io/CP/Services/subscriberimportapi
776	1	2021-02-07 17:47:32.259309+00	test	\N	\N	https://gitlab.aweber.io/CP/Services/subscriberproxy
777	1	2021-02-07 17:47:32.38442+00	test	\N	\N	https://gitlab.aweber.io/CP/Services/tagging
737	4	2021-02-07 17:47:28.047648+00	test	\N	\N	https://sentry.io/organizations/aweber-communications/issues/?project=42747
738	2	2021-02-07 17:47:28.119104+00	test	\N	\N	https://grafana.aweber.io/d/000000530/account-logins
738	4	2021-02-07 17:47:28.192193+00	test	\N	\N	https://sentry.io/organizations/aweber-communications/issues/?project=42747
739	1	2021-02-07 17:47:28.264144+00	test	\N	\N	https://gitlab.aweber.io/CP/applications/subscriber-import
744	4	2021-02-07 17:47:28.69274+00	test	\N	\N	https://sentry.io/organizations/aweber-communications/issues/?project=1491236
745	1	2021-02-07 17:47:28.764403+00	test	\N	\N	https://gitlab.aweber.io/CP/applications/user-profile-client
749	4	2021-02-07 17:47:29.119873+00	test	\N	\N	https://sentry.io/organizations/aweber-communications/issues/?project=1249804
750	2	2021-02-07 17:47:29.192752+00	test	\N	\N	https://grafana.aweber.io/d/000000273/coi-consumer
750	4	2021-02-07 17:47:29.265164+00	test	\N	\N	https://sentry.io/organizations/aweber-communications/issues/?project=1418959
751	1	2021-02-07 17:47:29.333173+00	test	\N	\N	https://gitlab.aweber.io/CP/Consumers/core-consumers
752	2	2021-02-07 17:47:29.402872+00	test	\N	\N	https://grafana.aweber.io/d/000000225/new-subscriber-notification-consumer
752	4	2021-02-07 17:47:29.471442+00	test	\N	\N	https://sentry.io/organizations/aweber-communications/issues/?project=1361175
753	2	2021-02-07 17:47:29.539757+00	test	\N	\N	https://grafana.aweber.io/d/Kse5ArgWk/subscriber-import-processing#panel-24
753	4	2021-02-07 17:47:29.601805+00	test	\N	\N	https://sentry.io/organizations/aweber-communications/issues/?project=1436167
754	2	2021-02-07 17:47:29.668492+00	test	\N	\N	https://grafana.aweber.io/d/Kse5ArgWk/subscriber-import-processing
754	4	2021-02-07 17:47:29.734362+00	test	\N	\N	https://sentry.io/organizations/aweber-communications/issues/?project=1442501
755	1	2021-02-07 17:47:29.80754+00	test	\N	\N	https://gitlab.aweber.io/CP/Consumers/subscriber-rebuild
756	1	2021-02-07 17:47:29.9451+00	test	\N	\N	https://gitlab.aweber.io/CP/Consumers/subscriber-sync
757	1	2021-02-07 17:47:30.078579+00	test	\N	\N	https://gitlab.aweber.io/CP/Consumers/subscriber-tag-sync
758	1	2021-02-07 17:47:30.224172+00	test	\N	\N	https://gitlab.aweber.io/CP/Consumers/tagpublisher
759	2	2021-02-07 17:47:30.307266+00	test	\N	\N	https://grafana.aweber.io/d/000000221/addlead-uploader
761	1	2021-02-07 17:47:30.514982+00	test	\N	\N	https://gitlab.aweber.io/CP/Services/awlists
762	2	2021-02-07 17:47:30.587027+00	test	\N	\N	https://grafana.aweber.io/d/000000031/awsubscribers-dashboard
762	4	2021-02-07 17:47:30.653805+00	test	\N	\N	https://sentry.io/organizations/aweber-communications/issues/?project=276177
763	2	2021-02-07 17:47:30.723487+00	test	\N	\N	https://grafana.aweber.io/d/000000053/domain-validator-web-form-typo
764	1	2021-02-07 17:47:30.883681+00	test	\N	\N	https://gitlab.aweber.io/CP/Services/email-verification
766	1	2021-02-07 17:47:31.101371+00	test	\N	\N	https://gitlab.aweber.io/CP/Services/geoip
769	1	2021-02-07 17:47:31.388014+00	test	\N	\N	https://gitlab.aweber.io/CP/Services/recipient
770	1	2021-02-07 17:47:31.523919+00	test	\N	\N	https://gitlab.aweber.io/CP/Services/s4
771	1	2021-02-07 17:47:31.591767+00	test	\N	\N	https://gitlab.aweber.io/CP/Services/search_recipients
772	2	2021-02-07 17:47:31.65593+00	test	\N	\N	https://grafana.aweber.io/d/000000352/search-proxy
772	4	2021-02-07 17:47:31.724454+00	test	\N	\N	https://sentry.io/organizations/aweber-communications/issues/?project=136599
773	2	2021-02-07 17:47:31.806751+00	test	\N	\N	https://grafana.aweber.io/d/zf7CbyzZz/session-auth-service
773	4	2021-02-07 17:47:31.876923+00	test	\N	\N	https://sentry.io/organizations/aweber-communications/issues/?project=1448827
774	2	2021-02-07 17:47:31.943631+00	test	\N	\N	https://grafana.aweber.io/d/000000357/subscriber-search
774	4	2021-02-07 17:47:32.012965+00	test	\N	\N	https://sentry.io/organizations/aweber-communications/issues/?project=155960
775	2	2021-02-07 17:47:32.08444+00	test	\N	\N	https://grafana.aweber.io/d/000000322/subscriber-import-api
775	4	2021-02-07 17:47:32.154826+00	test	\N	\N	https://sentry.io/organizations/aweber-communications/issues/?project=106277
776	2	2021-02-07 17:47:32.221846+00	test	\N	\N	https://grafana.aweber.io/d/000000354/subscriber-proxy
776	4	2021-02-07 17:47:32.289261+00	test	\N	\N	https://sentry.io/organizations/aweber-communications/issues/?project=116895
777	2	2021-02-07 17:47:32.351277+00	test	\N	\N	https://grafana.aweber.io/d/000000241/tagging-service
777	4	2021-02-07 17:47:32.414046+00	test	\N	\N	https://sentry.io/organizations/aweber-communications/issues/?project=43839
778	2	2021-02-07 17:47:32.477409+00	test	\N	\N	https://grafana.aweber.io/d/000000213/tagging-proxy-dashboard
778	4	2021-02-07 17:47:32.536269+00	test	\N	\N	https://sentry.io/organizations/aweber-communications/issues/?project=62301
779	1	2021-02-07 17:47:32.599208+00	test	\N	\N	https://gitlab.aweber.io/CP/Services/verifications
780	1	2021-02-07 17:47:32.722719+00	test	\N	\N	https://gitlab.aweber.io/CP/user-management
781	1	2021-02-07 17:47:32.878729+00	test	\N	\N	https://gitlab.aweber.io/CP/commissions-processor
782	2	2021-02-07 17:47:32.948722+00	test	\N	\N	https://grafana.aweber.io/d/000000382/mapping-service
782	4	2021-02-07 17:47:33.014512+00	test	\N	\N	https://sentry.io/organizations/aweber-communications/issues/?project=43824
783	2	2021-02-07 17:47:33.083668+00	test	\N	\N	https://grafana.aweber.io/d/LUo14I4ik/bulk-tagging-service
783	4	2021-02-07 17:47:33.163811+00	test	\N	\N	https://sentry.io/organizations/aweber-communications/issues/?project=1253454
784	1	2021-02-07 17:47:33.237695+00	test	\N	\N	https://gitlab.aweber.io/Mobile/services/core-api/core-api
785	1	2021-02-07 17:47:33.322153+00	test	\N	\N	https://gitlab.aweber.io/CP/archive/segment
786	5	2021-02-07 17:47:33.480976+00	test	\N	\N	https://sonarqube.aweber.io/dashboard?id=conv%3Aaccount-settings-client
787	1	2021-02-07 17:47:33.54939+00	test	\N	\N	https://gitlab.aweber.io/conv/services/affiliate-cookier
788	2	2021-02-07 17:47:33.621259+00	test	\N	\N	https://grafana.aweber.io/d/Woc8dVxik/consumers-dashboard?orgId=1
788	4	2021-02-07 17:47:33.690651+00	test	\N	\N	https://sentry.io/organizations/aweber-communications/issues/?project=1304158
790	1	2021-02-07 17:47:33.913789+00	test	\N	\N	https://gitlab.aweber.io/conv/services/awaccounts
791	2	2021-02-07 17:47:33.993993+00	test	\N	\N	https://grafana.aweber.io/d/000000320/billing-processor?orgId=1&refresh=5m
791	4	2021-02-07 17:47:34.068073+00	test	\N	\N	https://sentry.io/organizations/aweber-communications/issues/?project=98527
792	1	2021-02-07 17:47:34.142962+00	test	\N	\N	https://gitlab.aweber.io/conv/applications/cancellations
793	1	2021-02-07 17:47:34.209157+00	test	\N	\N	https://gitlab.aweber.io/conv/applications/cancellations
794	1	2021-02-07 17:47:34.277439+00	test	\N	\N	https://gitlab.aweber.io/conv/cc-notification-publisher
795	1	2021-02-07 17:47:34.337215+00	test	\N	\N	https://gitlab.aweber.io/conv/consumers/ccnotifier
796	2	2021-02-07 17:47:34.39877+00	test	\N	\N	https://grafana.aweber.io/d/BRbd-vuik/commission-junction?orgId=1
796	4	2021-02-07 17:47:34.456137+00	test	\N	\N	https://sentry.io/organizations/aweber-communications/issues/?project=1377983
797	1	2021-02-07 17:47:34.516526+00	test	\N	\N	https://gitlab.aweber.io/conv/services/commission-junction
797	5	2021-02-07 17:47:34.578354+00	test	\N	\N	https://sonarqube.aweber.io/dashboard?id=conv%3Acommission_junction
798	1	2021-02-07 17:47:34.638971+00	test	\N	\N	https://gitlab.aweber.io/conv/corporate-notifications
799	1	2021-02-07 17:47:34.707313+00	test	\N	\N	https://gitlab.aweber.io/conv/modules/credit-card-parse
778	1	2021-02-07 17:47:32.506757+00	test	\N	\N	https://gitlab.aweber.io/CP/Services/taggingproxy
779	4	2021-02-07 17:47:32.62748+00	test	\N	\N	https://sentry.io/organizations/aweber-communications/issues/?project=1338862
780	2	2021-02-07 17:47:32.689966+00	test	\N	\N	https://grafana.aweber.io/d/qI77ytliz/user-management-service
780	4	2021-02-07 17:47:32.766718+00	test	\N	\N	https://sentry.io/organizations/aweber-communications/issues/?project=1397549
781	2	2021-02-07 17:47:32.841987+00	test	\N	\N	https://grafana.aweber.io/d/000000497/commissions-processor
782	1	2021-02-07 17:47:32.982563+00	test	\N	\N	https://gitlab.aweber.io/CP/mapping
783	1	2021-02-07 17:47:33.124373+00	test	\N	\N	https://gitlab.aweber.io/CP/bulk-tagging
785	4	2021-02-07 17:47:33.359325+00	test	\N	\N	https://sentry.io/organizations/aweber-communications/issues/?project=101668
786	1	2021-02-07 17:47:33.441489+00	test	\N	\N	https://gitlab.aweber.io/conv/clients/account-settings-client
788	1	2021-02-07 17:47:33.653124+00	test	\N	\N	https://gitlab.aweber.io/conv/consumers/auto-webform-consumer
788	5	2021-02-07 17:47:33.730727+00	test	\N	\N	https://sonarqube.aweber.io/dashboard?id=conv%3Aauto-webform
789	1	2021-02-07 17:47:33.799876+00	test	\N	\N	https://gitlab.aweber.io/conv/clients/automatic-template-creator
790	2	2021-02-07 17:47:33.876172+00	test	\N	\N	https://grafana.aweber.io/d/000000440/core-api-capi?orgId=1
791	1	2021-02-07 17:47:34.032866+00	test	\N	\N	https://gitlab.aweber.io/conv/jobs/billing-processor
796	1	2021-02-07 17:47:34.427694+00	test	\N	\N	https://gitlab.aweber.io/conv/consumers/commission-junction-consumer
797	4	2021-02-07 17:47:34.545946+00	test	\N	\N	https://sentry.io/organizations/aweber-communications/issues/?project=1378847
800	1	2021-02-07 17:47:34.820196+00	test	\N	\N	https://gitlab.aweber.io/conv/services/data-enrichment-api
801	1	2021-02-07 17:47:34.956545+00	test	\N	\N	https://gitlab.aweber.io/conv/data-enrichment-consumer
802	5	2021-02-07 17:47:35.095728+00	test	\N	\N	https://sonarqube.aweber.io/dashboard?id=conv%3Adeploy-client-to-s3
803	2	2021-02-07 17:47:35.164789+00	test	\N	\N	https://grafana.aweber.io/d/9AOjE0SZk/extraction-service?orgId=1
803	4	2021-02-07 17:47:35.233782+00	test	\N	\N	https://sentry.io/organizations/aweber-communications/issues/?project=1437140
804	1	2021-02-07 17:47:35.368881+00	test	\N	\N	https://gitlab.aweber.io/conv/modules/grafana-kissmetrics
805	2	2021-02-07 17:47:35.439852+00	test	\N	\N	https://grafana.aweber.io/d/000000470/kissmetrics-consumers?orgId=1
805	4	2021-02-07 17:47:35.511899+00	test	\N	\N	https://sentry.io/organizations/aweber-communications/issues/?project=183192
806	1	2021-02-07 17:47:35.584312+00	test	\N	\N	https://gitlab.aweber.io/conv/jobs/kissmetrics-scripts
807	1	2021-02-07 17:47:35.653448+00	test	\N	\N	https://gitlab.aweber.io/conv/list-automation-client
808	1	2021-02-07 17:47:35.798777+00	test	\N	\N	https://gitlab.aweber.io/conv/applications/nue
809	1	2021-02-07 17:47:35.943681+00	test	\N	\N	https://gitlab.aweber.io/conv/applications/nue
810	1	2021-02-07 17:47:36.083499+00	test	\N	\N	https://gitlab.aweber.io/conv/consumers/nue-complete-tag-consumer
811	1	2021-02-07 17:47:36.232687+00	test	\N	\N	https://gitlab.aweber.io/conv/consumers/onboarding-campaign-consumer
812	1	2021-02-07 17:47:36.379447+00	test	\N	\N	https://gitlab.aweber.io/conv/clients/payflowpro
813	2	2021-02-07 17:47:36.450039+00	test	\N	\N	https://grafana.aweber.io/d/Woc8dVxik/consumers-dashboard?orgId=1
815	1	2021-02-07 17:47:36.664652+00	test	\N	\N	https://gitlab.aweber.io/conv/services/service-limits
815	5	2021-02-07 17:47:36.731594+00	test	\N	\N	https://sonarqube.aweber.io/dashboard?id=conv%3Aservice-limits
816	2	2021-02-07 17:47:36.814659+00	test	\N	\N	https://grafana.aweber.io/d/BKN4ZaFGz/service-limits-dismisser?orgId=1
816	4	2021-02-07 17:47:36.88538+00	test	\N	\N	https://sentry.io/organizations/aweber-communications/issues/?project=5436351
817	1	2021-02-07 17:47:37.033332+00	test	\N	\N	https://gitlab.aweber.io/conv/jobs/service-limits-notifier
817	5	2021-02-07 17:47:37.098474+00	test	\N	\N	https://sonarqube.aweber.io/dashboard?id=conv%3Aservice-limits-notifier
818	2	2021-02-07 17:47:37.181725+00	test	\N	\N	https://grafana.aweber.io/d/vqm_m-VGk/service-measurement-consumers?orgId=1
818	5	2021-02-07 17:47:37.259842+00	test	\N	\N	https://sonarqube.aweber.io/dashboard?id=conv%3Aservice-measurement
819	2	2021-02-07 17:47:37.331363+00	test	\N	\N	https://grafana.aweber.io/d/XQbAsVNMk/session-termination-consumers?orgId=1&refresh=1m
819	4	2021-02-07 17:47:37.404411+00	test	\N	\N	https://sentry.io/organizations/aweber-communications/issues/?project=5384870
820	1	2021-02-07 17:47:37.555077+00	test	\N	\N	https://gitlab.aweber.io/conv/services/sessions
821	2	2021-02-07 17:47:37.632535+00	test	\N	\N	https://grafana.aweber.io/d/O2B4i5RZz/signup-service?orgId=1&refresh=30s
821	4	2021-02-07 17:47:37.709985+00	test	\N	\N	https://sentry.io/organizations/aweber-communications/issues/?project=1475686
822	1	2021-02-07 17:47:37.866317+00	test	\N	\N	https://gitlab.aweber.io/conv/services/subdomain
822	5	2021-02-07 17:47:37.937515+00	test	\N	\N	https://sonarqube.aweber.io/dashboard?id=conv%3Asubdomain
823	2	2021-02-07 17:47:38.014087+00	test	\N	\N	https://grafana.aweber.io/d/000000460/trial-account-processor?orgId=1
824	1	2021-02-07 17:47:38.199769+00	test	\N	\N	https://gitlab.aweber.io/conv/infrastructure/unauthenticated-kong
825	2	2021-02-07 17:47:38.280729+00	test	\N	\N	https://grafana.aweber.io/d/-V3ZRNMMk/webform-service?orgId=1
825	4	2021-02-07 17:47:38.35348+00	test	\N	\N	https://sentry.io/organizations/aweber-communications/issues/?project=1308465
826	1	2021-02-07 17:47:38.426538+00	test	\N	\N	https://gitlab.aweber.io/conv/webpage-spider
827	1	2021-02-07 17:47:38.499318+00	test	\N	\N	https://gitlab.aweber.io/conv/jobs/winback-promo-email
828	1	2021-02-07 17:47:38.57163+00	test	\N	\N	https://gitlab.aweber.io/conv/www
829	1	2021-02-07 17:47:38.71562+00	test	\N	\N	https://gitlab.aweber.io/edeliv/Applications/autoresponse-worker
830	2	2021-02-07 17:47:38.797165+00	test	\N	\N	https://grafana.aweber.io/d/ULmyr1Jiz/broadcast-notification-consumers?orgId=1
830	4	2021-02-07 17:47:38.871761+00	test	\N	\N	https://sentry.io/organizations/aweber-communications/issues/?project=1296772
831	2	2021-02-07 17:47:38.945371+00	test	\N	\N	https://grafana.aweber.io/d/ULmyr1Jiz/broadcast-notification-consumers?orgId=1
831	4	2021-02-07 17:47:39.017673+00	test	\N	\N	https://sentry.io/organizations/aweber-communications/issues/?project=1307399
832	2	2021-02-07 17:47:39.09497+00	test	\N	\N	https://grafana.aweber.io/d/000000538/broadcaster?orgId=1&refresh=1m
832	4	2021-02-07 17:47:39.174782+00	test	\N	\N	https://sentry.io/organizations/aweber-communications/issues/?project=270769
833	2	2021-02-07 17:47:39.2577+00	test	\N	\N	https://grafana.aweber.io/d/000000186/composer-consumer?orgId=1
833	4	2021-02-07 17:47:39.330671+00	test	\N	\N	https://sentry.io/organizations/aweber-communications/issues/?project=283191
834	2	2021-02-07 17:47:39.404141+00	test	\N	\N	https://grafana.aweber.io/d/KNwtfWWWk/deliverability-rollup-processing?orgId=1&refresh=30s
834	4	2021-02-07 17:47:39.473631+00	test	\N	\N	https://sentry.io/organizations/aweber-communications/issues/?project=1455454
835	1	2021-02-07 17:47:39.615063+00	test	\N	\N	https://gitlab.aweber.io/edeliv/Applications/DomainReputation/dr-results
836	1	2021-02-07 17:47:39.764966+00	test	\N	\N	https://gitlab.aweber.io/edeliv/Applications/DomainReputation/dr-url-scraper
836	5	2021-02-07 17:47:39.843245+00	test	\N	\N	https://sonarqube.aweber.io/dashboard?id=edeliv%3Adr-url-scraper
1025	1	2021-02-07 17:47:59.443485+00	test	\N	\N	https://gitlab.aweber.io/PSE/Applications/admin-v2
800	2	2021-02-07 17:47:34.782891+00	test	\N	\N	https://grafana.aweber.io/d/MInQjI-mz/data-enrichment-api?orgId=1&refresh=30s
800	4	2021-02-07 17:47:34.854945+00	test	\N	\N	https://sentry.io/organizations/aweber-communications/issues/?project=1299364
801	2	2021-02-07 17:47:34.924888+00	test	\N	\N	https://grafana.aweber.io/d/TJnJ0aciz/data-enrichment-consumers?orgId=1&refresh=1m
801	4	2021-02-07 17:47:34.992986+00	test	\N	\N	https://sentry.io/organizations/aweber-communications/issues/?project=1254102
802	1	2021-02-07 17:47:35.057978+00	test	\N	\N	https://gitlab.aweber.io/conv/applications/deploy-client-to-s3
803	1	2021-02-07 17:47:35.200125+00	test	\N	\N	https://gitlab.aweber.io/conv/services/extraction
803	5	2021-02-07 17:47:35.267753+00	test	\N	\N	https://sonarqube.aweber.io/dashboard?id=conv%3Aextraction
804	2	2021-02-07 17:47:35.335066+00	test	\N	\N	https://grafana.aweber.io/d/000000506/conversions-kissmetrics?orgId=1
805	1	2021-02-07 17:47:35.475036+00	test	\N	\N	https://gitlab.aweber.io/conv/consumers/kissmetrics
807	4	2021-02-07 17:47:35.689174+00	test	\N	\N	https://sentry.io/organizations/aweber-communications/issues/?project=1284484
808	2	2021-02-07 17:47:35.762419+00	test	\N	\N	https://grafana.aweber.io/d/000000017/nue?orgId=1
808	4	2021-02-07 17:47:35.835893+00	test	\N	\N	https://sentry.io/organizations/aweber-communications/issues/?project=250267
809	2	2021-02-07 17:47:35.908921+00	test	\N	\N	https://grafana.aweber.io/d/000000017/nue?orgId=1
809	4	2021-02-07 17:47:35.981395+00	test	\N	\N	https://sentry.io/organizations/aweber-communications/issues/?project=250267
810	2	2021-02-07 17:47:36.046685+00	test	\N	\N	https://grafana.aweber.io/d/Woc8dVxik/consumers-dashboard?orgId=1
810	4	2021-02-07 17:47:36.121743+00	test	\N	\N	https://sentry.io/organizations/aweber-communications/issues/?project=1288965
811	2	2021-02-07 17:47:36.198017+00	test	\N	\N	https://grafana.aweber.io/d/Woc8dVxik/consumers-dashboard?orgId=1
811	4	2021-02-07 17:47:36.270549+00	test	\N	\N	https://sentry.io/organizations/aweber-communications/issues/?project=1223045
812	2	2021-02-07 17:47:36.343427+00	test	\N	\N	https://grafana.aweber.io/d/000000319/cde-payflow-pro-billing?orgId=1&refresh=30s
813	1	2021-02-07 17:47:36.487118+00	test	\N	\N	https://gitlab.aweber.io/conv/consumers/pageview-consumer
814	1	2021-02-07 17:47:36.558875+00	test	\N	\N	https://gitlab.aweber.io/conv/reset-password-email-metrics
815	2	2021-02-07 17:47:36.631157+00	test	\N	\N	https://grafana.aweber.io/d/sv8-4rnMk/service-limits-api?orgId=1&refresh=5m
815	4	2021-02-07 17:47:36.700444+00	test	\N	\N	https://sentry.io/organizations/aweber-communications/issues/?project=5352517
816	1	2021-02-07 17:47:36.852083+00	test	\N	\N	https://gitlab.aweber.io/conv/consumers/service-limits-dismisser
816	5	2021-02-07 17:47:36.923398+00	test	\N	\N	https://sonarqube.aweber.io/dashboard?id=int%3Aservice-limits-dismisser
817	2	2021-02-07 17:47:36.993978+00	test	\N	\N	https://grafana.aweber.io/d/wGLaiJOMz/service-limits-notifier?orgId=1&refresh=5m
817	4	2021-02-07 17:47:37.065453+00	test	\N	\N	https://sentry.io/organizations/aweber-communications/issues/?project=5395834
818	1	2021-02-07 17:47:37.21849+00	test	\N	\N	https://gitlab.aweber.io/conv/consumers/service-measurement-consumers
819	1	2021-02-07 17:47:37.366802+00	test	\N	\N	https://gitlab.aweber.io/conv/consumers/session-termination-consumer
819	5	2021-02-07 17:47:37.442191+00	test	\N	\N	https://sonarqube.aweber.io/dashboard?id=conv%3Asession-termination-consumer
820	2	2021-02-07 17:47:37.520885+00	test	\N	\N	https://grafana.aweber.io/d/000000095/session-service?orgId=1&refresh=5m
821	1	2021-02-07 17:47:37.672004+00	test	\N	\N	https://gitlab.aweber.io/conv/services/signup
821	5	2021-02-07 17:47:37.756418+00	test	\N	\N	https://sonarqube.aweber.io/dashboard?id=conv%3Asignup
822	2	2021-02-07 17:47:37.833907+00	test	\N	\N	https://grafana.aweber.io/d/yIgOnHGMz/subdomain?orgId=1&refresh=30s
822	4	2021-02-07 17:47:37.899196+00	test	\N	\N	https://sentry.io/organizations/aweber-communications/issues/?project=5283142
823	1	2021-02-07 17:47:38.052061+00	test	\N	\N	https://gitlab.aweber.io/conv/trial-account-processor
824	2	2021-02-07 17:47:38.165298+00	test	\N	\N	https://grafana.aweber.io/d/Yfi0iSgWz/unauthenticated-kong?orgId=1
825	1	2021-02-07 17:47:38.318612+00	test	\N	\N	https://gitlab.aweber.io/conv/services/webform-service
828	4	2021-02-07 17:47:38.608236+00	test	\N	\N	https://sentry.io/organizations/aweber-communications/issues/?project=211542
829	2	2021-02-07 17:47:38.679291+00	test	\N	\N	https://grafana.aweber.io/d/BXxavlImk/autoresponse-workers?orgId=1
830	1	2021-02-07 17:47:38.839412+00	test	\N	\N	https://gitlab.aweber.io/edeliv/Applications/broadcast-notification-scheduler
831	1	2021-02-07 17:47:38.982109+00	test	\N	\N	https://gitlab.aweber.io/edeliv/Applications/broadcast-notification-sender
832	1	2021-02-07 17:47:39.137108+00	test	\N	\N	https://gitlab.aweber.io/edeliv/Applications/broadcaster
833	1	2021-02-07 17:47:39.294341+00	test	\N	\N	https://gitlab.aweber.io/edeliv/Applications/composer
834	1	2021-02-07 17:47:39.439895+00	test	\N	\N	https://gitlab.aweber.io/edeliv/Applications/deliverability-rollup
834	5	2021-02-07 17:47:39.507532+00	test	\N	\N	https://sonarqube.aweber.io/dashboard?id=edeliv%3Adeliverability-rollup
835	2	2021-02-07 17:47:39.578206+00	test	\N	\N	https://grafana.aweber.io/d/000000478/domain-reputation-3-3-results-processor?orgId=1&refresh=1m
835	4	2021-02-07 17:47:39.649445+00	test	\N	\N	https://sentry.io/organizations/aweber-communications/issues/?project=5193694
836	2	2021-02-07 17:47:39.726653+00	test	\N	\N	https://grafana.aweber.io/d/000000472/domain-reputation-1-3-scraper?orgId=1&refresh=1m
836	4	2021-02-07 17:47:39.800771+00	test	\N	\N	https://sentry.io/organizations/aweber-communications/issues/?project=1356239
837	1	2021-02-07 17:47:39.951702+00	test	\N	\N	https://gitlab.aweber.io/edeliv/Applications/DomainReputation/sift-url-publisher
838	2	2021-02-07 17:47:40.023282+00	test	\N	\N	https://grafana.aweber.io/d/-bnRnqQiz/momentum-dashboard?orgId=1&refresh=5m
839	1	2021-02-07 17:47:40.175151+00	test	\N	\N	https://gitlab.aweber.io/edeliv/Applications/reputation/hearsay
840	2	2021-02-07 17:47:40.259956+00	test	\N	\N	https://grafana.aweber.io/d/PJwx57FGz/reputation-operational-dashboard?orgId=1
841	1	2021-02-07 17:47:40.396153+00	test	\N	\N	https://gitlab.aweber.io/edeliv/Applications/sender-authentication-consumer
842	2	2021-02-07 17:47:40.466305+00	test	\N	\N	https://grafana.aweber.io/d/hS_k1a5ik/sift-content-publisher?orgId=1
842	5	2021-02-07 17:47:40.538652+00	test	\N	\N	https://sonarqube.aweber.io/dashboard?id=edeliv%3Asift-message-content-publisher
843	2	2021-02-07 17:47:40.609203+00	test	\N	\N	https://grafana.aweber.io/d/000000160/spooling-consumer?orgId=1&refresh=5m
843	4	2021-02-07 17:47:40.68249+00	test	\N	\N	https://sentry.io/organizations/aweber-communications/issues/?project=307110
844	2	2021-02-07 17:47:40.763162+00	test	\N	\N	https://grafana.aweber.io/d/px73Dg2Mz/web-push-amplifier-consumer?orgId=1
844	4	2021-02-07 17:47:40.841428+00	test	\N	\N	https://sentry.io/organizations/aweber-communications/issues/?project=5499344
845	2	2021-02-07 17:47:40.91312+00	test	\N	\N	https://grafana.aweber.io/d/UNIsXwIMz/web-push-sender-consumer?orgId=1
845	4	2021-02-07 17:47:40.984164+00	test	\N	\N	https://sentry.io/organizations/aweber-communications/issues/?project=5390192
846	1	2021-02-07 17:47:41.055971+00	test	\N	\N	https://gitlab.aweber.io/edeliv/QA/broadcast-notification-test
847	2	2021-02-07 17:47:41.132073+00	test	\N	\N	https://grafana.aweber.io/d/000000436/email-validation-system-dashboard?orgId=1
847	4	2021-02-07 17:47:41.209795+00	test	\N	\N	https://sentry.io/organizations/aweber-communications/issues/?project=1860042
837	2	2021-02-07 17:47:39.916216+00	test	\N	\N	https://grafana.aweber.io/d/A75EP8tiz/sift-url-publisher-consumer?orgId=1&refresh=1m
838	1	2021-02-07 17:47:40.058061+00	test	\N	\N	https://gitlab.aweber.io/edeliv/Applications/momentum-stats-consumers
839	2	2021-02-07 17:47:40.1379+00	test	\N	\N	https://grafana.aweber.io/d/000000181/hearsay?orgId=1
840	1	2021-02-07 17:47:40.291933+00	test	\N	\N	https://gitlab.aweber.io/edeliv/Applications/reputation/reputation-workers
841	2	2021-02-07 17:47:40.365393+00	test	\N	\N	https://grafana.aweber.io/d/ej-gUjUWz/sender-authentication-consumer?orgId=1
842	1	2021-02-07 17:47:40.50304+00	test	\N	\N	https://gitlab.aweber.io/edeliv/Applications/sift-message-content-publisher
843	1	2021-02-07 17:47:40.646924+00	test	\N	\N	https://gitlab.aweber.io/edeliv/Applications/spoolconsumer
844	1	2021-02-07 17:47:40.796956+00	test	\N	\N	https://gitlab.aweber.io/edeliv/Applications/web-push-amplifier
845	1	2021-02-07 17:47:40.947307+00	test	\N	\N	https://gitlab.aweber.io/edeliv/Applications/web-push-sender
847	1	2021-02-07 17:47:41.171224+00	test	\N	\N	https://gitlab.aweber.io/edeliv/QA/messagevalidator
849	1	2021-02-07 17:47:41.412692+00	test	\N	\N	https://gitlab.aweber.io/edeliv/Applications/amp-broadcast
850	1	2021-02-07 17:47:41.556978+00	test	\N	\N	https://gitlab.aweber.io/edeliv/Applications/autohold
851	1	2021-02-07 17:47:41.69531+00	test	\N	\N	https://gitlab.aweber.io/edeliv/Applications/broadcast-segment
851	5	2021-02-07 17:47:41.765727+00	test	\N	\N	https://sonarqube.aweber.io/dashboard?id=edeliv%3Abroadcast-segment
852	2	2021-02-07 17:47:41.843873+00	test	\N	\N	https://grafana.aweber.io/d/1U3RhdFZz/broadcast-starter?orgId=1
852	4	2021-02-07 17:47:41.913523+00	test	\N	\N	https://sentry.io/organizations/aweber-communications/issues/?project=1449932
853	2	2021-02-07 17:47:41.983041+00	test	\N	\N	https://grafana.aweber.io/d/000000424/bulk-subscriber?orgId=1&refresh=5s
853	4	2021-02-07 17:47:42.054838+00	test	\N	\N	https://sentry.io/organizations/aweber-communications/issues/?project=197909
854	2	2021-02-07 17:47:42.128902+00	test	\N	\N	https://grafana.aweber.io/d/000000390/clicktracking-service?orgId=1&refresh=10s
854	4	2021-02-07 17:47:42.198522+00	test	\N	\N	https://sentry.io/organizations/aweber-communications/issues/?project=1234484
855	1	2021-02-07 17:47:42.27742+00	test	\N	\N	https://gitlab.aweber.io/edeliv/Applications/fixtureapi
857	1	2021-02-07 17:47:42.486788+00	test	\N	\N	https://gitlab.aweber.io/edeliv/Applications/routing
857	5	2021-02-07 17:47:42.558632+00	test	\N	\N	https://sonarqube.aweber.io/dashboard?id=edeliv%3Arouting
858	2	2021-02-07 17:47:42.63163+00	test	\N	\N	https://grafana.aweber.io/d/ZUViywTik/send-test?orgId=1
858	4	2021-02-07 17:47:42.698222+00	test	\N	\N	https://sentry.io/organizations/aweber-communications/issues/?project=1283427
859	2	2021-02-07 17:47:42.768051+00	test	\N	\N	https://grafana.aweber.io/d/nlaVNOfZz/sender-authentication?orgId=1&refresh=30s
859	4	2021-02-07 17:47:42.85399+00	test	\N	\N	https://sentry.io/organizations/aweber-communications/issues/?project=1836826
860	1	2021-02-07 17:47:42.925426+00	test	\N	\N	https://gitlab.aweber.io/edeliv/Applications/validation
861	1	2021-02-07 17:47:43.067934+00	test	\N	\N	https://gitlab.aweber.io/edeliv/Applications/web-push
862	1	2021-02-07 17:47:43.211801+00	test	\N	\N	https://gitlab.aweber.io/edeliv/Applications/web-push-subscriber
863	1	2021-02-07 17:47:43.368059+00	test	\N	\N	https://gitlab.aweber.io/edeliv/Applications/web-push-view
864	1	2021-02-07 17:47:43.502859+00	test	\N	\N	https://gitlab.aweber.io/edeliv/Applications/DomainReputation/dr-poller
867	1	2021-02-07 17:47:43.787502+00	test	\N	\N	https://gitlab.aweber.io/edeliv/Applications/google-postmaster-scraper
868	1	2021-02-07 17:47:43.861088+00	test	\N	\N	https://gitlab.aweber.io/edeliv/Applications/momentum-configuration-generator
869	1	2021-02-07 17:47:43.999093+00	test	\N	\N	https://gitlab.aweber.io/edeliv/Applications/reputation/augur
870	2	2021-02-07 17:47:44.069894+00	test	\N	\N	https://grafana.aweber.io/d/xvZmCdCiz/reputation-mongo-cron?orgId=1
870	4	2021-02-07 17:47:44.143524+00	test	\N	\N	https://sentry.io/organizations/aweber-communications/issues/?project=1408759
871	1	2021-02-07 17:47:44.213751+00	test	\N	\N	https://gitlab.aweber.io/edeliv/Applications/reputation/reputation-rollups
872	2	2021-02-07 17:47:44.291642+00	test	\N	\N	https://grafana.aweber.io/d/000000477/deliverability-email-delivery-trends?orgId=1
873	1	2021-02-07 17:47:44.432558+00	test	\N	\N	https://gitlab.aweber.io/edeliv/Applications/snds-processor
874	1	2021-02-07 17:47:44.501224+00	test	\N	\N	https://gitlab.aweber.io/edeliv/data-science/csleads_jira_report
875	1	2021-02-07 17:47:44.571827+00	test	\N	\N	https://gitlab.aweber.io/edeliv/Docker/passive_momentum_queue_check
876	1	2021-02-07 17:47:44.639222+00	test	\N	\N	https://gitlab.aweber.io/edeliv/QA/mailpoll
901	1	2021-02-07 17:47:46.537896+00	test	\N	\N	https://gitlab.aweber.io/edeliv/Libraries/perl/libredcache-perl
902	1	2021-02-07 17:47:46.611037+00	test	\N	\N	https://gitlab.aweber.io/edeliv/Libraries/perl/librediscluster-perl
903	1	2021-02-07 17:47:46.671776+00	test	\N	\N	https://gitlab.aweber.io/edeliv/Libraries/perl/perl-JLogShovel
904	1	2021-02-07 17:47:46.734731+00	test	\N	\N	https://gitlab.aweber.io/edeliv/Libraries/throttler
905	1	2021-02-07 17:47:46.818159+00	test	\N	\N	https://gitlab.aweber.io/edeliv/operations/aw-mock
906	1	2021-02-07 17:47:46.89751+00	test	\N	\N	https://gitlab.aweber.io/edeliv/operations/libaw-statsd-perl
907	1	2021-02-07 17:47:46.966116+00	test	\N	\N	https://gitlab.aweber.io/edeliv/operations/omnipitr
908	1	2021-02-07 17:47:47.031685+00	test	\N	\N	https://gitlab.aweber.io/edeliv/Tools/aw-ehawk-talon
909	1	2021-02-07 17:47:47.100411+00	test	\N	\N	https://gitlab.aweber.io/edeliv/3rdParty/statsd
910	1	2021-02-07 17:47:47.174142+00	test	\N	\N	https://gitlab.aweber.io/edeliv/Applications/corporate-mailer
911	1	2021-02-07 17:47:47.241555+00	test	\N	\N	https://gitlab.aweber.io/edeliv/config-management/ansible-playbooks
912	1	2021-02-07 17:47:47.324762+00	test	\N	\N	https://gitlab.aweber.io/edeliv/config-management/ansible-roles/aweber.momentum
913	1	2021-02-07 17:47:47.397395+00	test	\N	\N	https://gitlab.aweber.io/edeliv/config-management/edeliv-4947-momentum-svn-replacement-pilot
914	1	2021-02-07 17:47:47.470629+00	test	\N	\N	https://gitlab.aweber.io/edeliv/config-management/rabbitmq-definitions
915	1	2021-02-07 17:47:47.544053+00	test	\N	\N	https://gitlab.aweber.io/edeliv/config-management/rundeck-projects
916	1	2021-02-07 17:47:47.616331+00	test	\N	\N	https://gitlab.aweber.io/edeliv/data-science/production_classifier_notebooks
917	1	2021-02-07 17:47:47.687638+00	test	\N	\N	https://gitlab.aweber.io/edeliv/Docker/abusive-import-classifier
918	1	2021-02-07 17:47:47.764525+00	test	\N	\N	https://gitlab.aweber.io/edeliv/Docker/alpine-python3-testing
919	1	2021-02-07 17:47:47.836274+00	test	\N	\N	https://gitlab.aweber.io/edeliv/Docker/edeliv-perl-5-18-2
920	1	2021-02-07 17:47:47.910337+00	test	\N	\N	https://gitlab.aweber.io/edeliv/Docker/edeliv-python-test-2-6
921	1	2021-02-07 17:47:47.980783+00	test	\N	\N	https://gitlab.aweber.io/edeliv/Docker/edeliv-python-test-2-7
922	1	2021-02-07 17:47:48.045307+00	test	\N	\N	https://gitlab.aweber.io/edeliv/Docker/python-reputation-2.7
923	1	2021-02-07 17:47:48.117232+00	test	\N	\N	https://gitlab.aweber.io/edeliv/edeliv-5595-identify-jinja-templates
924	1	2021-02-07 17:47:48.19114+00	test	\N	\N	https://gitlab.aweber.io/edeliv/edeliv-6208-scheduler-audit
925	1	2021-02-07 17:47:48.268051+00	test	\N	\N	https://gitlab.aweber.io/edeliv/Libraries/perl/awbin
848	1	2021-02-07 17:47:41.302319+00	test	\N	\N	https://gitlab.aweber.io/edeliv/Applications/reputation/reputation-ui
849	2	2021-02-07 17:47:41.376519+00	test	\N	\N	https://grafana.aweber.io/d/kmD5TYeZk/amp-broadcast?orgId=1&refresh=1m
849	4	2021-02-07 17:47:41.448702+00	test	\N	\N	https://sentry.io/organizations/aweber-communications/issues/?project=5171911
850	2	2021-02-07 17:47:41.523908+00	test	\N	\N	https://grafana.aweber.io/d/000000402/broadcast-autohold?orgId=1&refresh=5m
850	4	2021-02-07 17:47:41.58962+00	test	\N	\N	https://sentry.io/organizations/aweber-communications/issues/?project=172308
851	2	2021-02-07 17:47:41.6614+00	test	\N	\N	https://grafana.aweber.io/d/000000355/broadcast-segment?orgId=1&refresh=10s
851	4	2021-02-07 17:47:41.730818+00	test	\N	\N	https://sentry.io/organizations/aweber-communications/issues/?project=121110
852	1	2021-02-07 17:47:41.879306+00	test	\N	\N	https://gitlab.aweber.io/edeliv/Applications/broadcast-starter
853	1	2021-02-07 17:47:42.018992+00	test	\N	\N	https://gitlab.aweber.io/edeliv/Applications/bulk-subscriber
854	1	2021-02-07 17:47:42.164449+00	test	\N	\N	https://gitlab.aweber.io/edeliv/Applications/clicktracking
855	5	2021-02-07 17:47:42.310627+00	test	\N	\N	https://sonarqube.aweber.io/dashboard?id=Mobile%3Afixtureapi
856	1	2021-02-07 17:47:42.379302+00	test	\N	\N	https://gitlab.aweber.io/edeliv/Applications/reputation/reputation-api
857	2	2021-02-07 17:47:42.451708+00	test	\N	\N	https://grafana.aweber.io/d/000000227/routing-service?orgId=1&refresh=1m
857	4	2021-02-07 17:47:42.523926+00	test	\N	\N	https://sentry.io/organizations/aweber-communications/issues/?project=43838
858	1	2021-02-07 17:47:42.665679+00	test	\N	\N	https://gitlab.aweber.io/edeliv/Applications/send-test
859	1	2021-02-07 17:47:42.807112+00	test	\N	\N	https://gitlab.aweber.io/edeliv/Applications/sender-authentication
860	5	2021-02-07 17:47:42.96174+00	test	\N	\N	https://sonarqube.aweber.io/dashboard?id=edeliv%3Avalidation
861	2	2021-02-07 17:47:43.031216+00	test	\N	\N	https://grafana.aweber.io/d/2_AGm8MGz/web-push-service?orgId=1
861	4	2021-02-07 17:47:43.102907+00	test	\N	\N	https://sentry.io/organizations/aweber-communications/issues/?project=5316508
862	2	2021-02-07 17:47:43.178367+00	test	\N	\N	https://grafana.aweber.io/d/aOS2VQSGz/web-push-subscriber-service?orgId=1&refresh=1m
862	4	2021-02-07 17:47:43.262051+00	test	\N	\N	https://sentry.io/organizations/aweber-communications/issues/?project=5316523
863	2	2021-02-07 17:47:43.331385+00	test	\N	\N	https://grafana.aweber.io/d/QQKfuLHMz/web-push-view-service?orgId=1
863	4	2021-02-07 17:47:43.400427+00	test	\N	\N	https://sentry.io/organizations/aweber-communications/issues/?project=5316521
864	2	2021-02-07 17:47:43.469712+00	test	\N	\N	https://grafana.aweber.io/d/000000475/domain-reputation-2-3-poller?orgId=1&refresh=5m
864	4	2021-02-07 17:47:43.535213+00	test	\N	\N	https://sentry.io/organizations/aweber-communications/issues/?project=5193732
865	1	2021-02-07 17:47:43.606804+00	test	\N	\N	https://gitlab.aweber.io/edeliv/Applications/DomainReputation/links_analyzer
866	1	2021-02-07 17:47:43.676212+00	test	\N	\N	https://gitlab.aweber.io/edeliv/Applications/DomainReputation/phishtank-updater
867	2	2021-02-07 17:47:43.755227+00	test	\N	\N	https://grafana.aweber.io/d/000000477/deliverability-email-delivery-trends?orgId=1
868	5	2021-02-07 17:47:43.895265+00	test	\N	\N	https://sonarqube.aweber.io/dashboard?id=edeliv%3Amomentum-configuration-generator
869	2	2021-02-07 17:47:43.963576+00	test	\N	\N	https://grafana.aweber.io/d/rrnuVecmz/augur-workers?orgId=1
870	1	2021-02-07 17:47:44.107278+00	test	\N	\N	https://gitlab.aweber.io/edeliv/Applications/reputation/reputation-mongo-cron
872	1	2021-02-07 17:47:44.323009+00	test	\N	\N	https://gitlab.aweber.io/edeliv/Applications/return-path-processor
873	2	2021-02-07 17:47:44.397914+00	test	\N	\N	https://grafana.aweber.io/d/000000477/deliverability-email-delivery-trends?orgId=1
876	4	2021-02-07 17:47:44.676618+00	test	\N	\N	https://sentry.io/organizations/aweber-communications/issues/?project=198781
877	1	2021-02-07 17:47:44.754126+00	test	\N	\N	https://gitlab.aweber.io/edeliv/Tools/unsubscribe_blocked_email
878	1	2021-02-07 17:47:44.821014+00	test	\N	\N	https://gitlab.aweber.io/edeliv/3rdParty/perl-Avro
879	1	2021-02-07 17:47:44.895449+00	test	\N	\N	https://gitlab.aweber.io/edeliv/3rdParty/perl-JLog
880	1	2021-02-07 17:47:44.966012+00	test	\N	\N	https://gitlab.aweber.io/edeliv/3rdParty/perl-Net-AMQP-RabbitMQ
881	1	2021-02-07 17:47:45.033843+00	test	\N	\N	https://gitlab.aweber.io/edeliv/Applications/corporate-notifications
882	1	2021-02-07 17:47:45.105669+00	test	\N	\N	https://gitlab.aweber.io/edeliv/Applications/reputation/reputation_models
883	1	2021-02-07 17:47:45.181601+00	test	\N	\N	https://gitlab.aweber.io/edeliv/Libraries/aweber-content-rendering
884	1	2021-02-07 17:47:45.263157+00	test	\N	\N	https://gitlab.aweber.io/edeliv/Libraries/awfabfiles
885	1	2021-02-07 17:47:45.338586+00	test	\N	\N	https://gitlab.aweber.io/edeliv/Libraries/base-event-worker
886	1	2021-02-07 17:47:45.411441+00	test	\N	\N	https://gitlab.aweber.io/edeliv/Libraries/conditional-content-prototypes
887	1	2021-02-07 17:47:45.487318+00	test	\N	\N	https://gitlab.aweber.io/edeliv/Libraries/connectionproxy
888	1	2021-02-07 17:47:45.558301+00	test	\N	\N	https://gitlab.aweber.io/edeliv/Libraries/connectionproxy-rabbitmq
889	1	2021-02-07 17:47:45.621145+00	test	\N	\N	https://gitlab.aweber.io/edeliv/Libraries/ecsocket
890	1	2021-02-07 17:47:45.690874+00	test	\N	\N	https://gitlab.aweber.io/edeliv/Libraries/email-validation
891	1	2021-02-07 17:47:45.767889+00	test	\N	\N	https://gitlab.aweber.io/edeliv/Libraries/geturl
892	1	2021-02-07 17:47:45.84181+00	test	\N	\N	https://gitlab.aweber.io/edeliv/Libraries/heavymetl
893	1	2021-02-07 17:47:45.915726+00	test	\N	\N	https://gitlab.aweber.io/edeliv/Libraries/jwty
894	1	2021-02-07 17:47:45.980772+00	test	\N	\N	https://gitlab.aweber.io/edeliv/Libraries/mailcontent
895	1	2021-02-07 17:47:46.060643+00	test	\N	\N	https://gitlab.aweber.io/edeliv/Libraries/metl
896	1	2021-02-07 17:47:46.13561+00	test	\N	\N	https://gitlab.aweber.io/edeliv/Libraries/mithril
897	1	2021-02-07 17:47:46.203121+00	test	\N	\N	https://gitlab.aweber.io/edeliv/Libraries/perl/libcog-perl
898	1	2021-02-07 17:47:46.290119+00	test	\N	\N	https://gitlab.aweber.io/edeliv/Libraries/perl/libdistredis-perl
899	1	2021-02-07 17:47:46.36185+00	test	\N	\N	https://gitlab.aweber.io/edeliv/Libraries/perl/libhashring-perl
900	1	2021-02-07 17:47:46.430566+00	test	\N	\N	https://gitlab.aweber.io/edeliv/Libraries/perl/libmemcached-libmemcached-perl
901	2	2021-02-07 17:47:46.503867+00	test	\N	\N	https://grafana.aweber.io/d/000000409/redcache-redis?orgId=1&refresh=1m
930	1	2021-02-07 17:47:48.678145+00	test	\N	\N	https://gitlab.aweber.io/edeliv/Libraries/perl/perl-Momentum-JLogShovel
931	1	2021-02-07 17:47:48.759246+00	test	\N	\N	https://gitlab.aweber.io/edeliv/QA/aweber-imbi
932	2	2021-02-07 17:47:48.829442+00	test	\N	\N	https://grafana.aweber.io/d/G_l9BAJWz/email-delivery-behave-tests?orgId=1
960	1	2021-02-07 17:47:50.939393+00	test	\N	\N	https://gitlab.aweber.io/edeliv/Tools/perl-momentum-log-parsers
961	2	2021-02-07 17:47:51.013026+00	test	\N	\N	https://grafana.aweber.io/d/000000361/broadcast-processing?orgId=1
964	4	2021-02-07 17:47:51.307916+00	test	\N	\N	https://sentry.io/organizations/aweber-communications/issues/?project=2130605
965	1	2021-02-07 17:47:51.444082+00	test	\N	\N	https://gitlab.aweber.io/integrations/services/aweber-auth
926	1	2021-02-07 17:47:48.335878+00	test	\N	\N	https://gitlab.aweber.io/edeliv/Libraries/perl/aweber-scripts
927	1	2021-02-07 17:47:48.409799+00	test	\N	\N	https://gitlab.aweber.io/edeliv/Libraries/perl/aweber-support
928	1	2021-02-07 17:47:48.49326+00	test	\N	\N	https://gitlab.aweber.io/edeliv/Libraries/perl/awlib
929	1	2021-02-07 17:47:48.567968+00	test	\N	\N	https://gitlab.aweber.io/edeliv/Libraries/perl/awutil
930	2	2021-02-07 17:47:48.640283+00	test	\N	\N	https://grafana.aweber.io/d/-bnRnqQiz/momentum-dashboard?orgId=1&refresh=5m
932	1	2021-02-07 17:47:48.875263+00	test	\N	\N	https://gitlab.aweber.io/edeliv/QA/behave-automation
933	1	2021-02-07 17:47:48.95135+00	test	\N	\N	https://gitlab.aweber.io/edeliv/QA/behave-subscriber-cleanup
934	1	2021-02-07 17:47:49.02281+00	test	\N	\N	https://gitlab.aweber.io/edeliv/QA/broadcast-notification-test-poller
935	1	2021-02-07 17:47:49.093685+00	test	\N	\N	https://gitlab.aweber.io/edeliv/QA/conditional-content-test-data
936	1	2021-02-07 17:47:49.170323+00	test	\N	\N	https://gitlab.aweber.io/edeliv/QA/k8-website-host
937	1	2021-02-07 17:47:49.241952+00	test	\N	\N	https://gitlab.aweber.io/edeliv/QA/routing-test
938	1	2021-02-07 17:47:49.322588+00	test	\N	\N	https://gitlab.aweber.io/edeliv/QA/trafficgenerator
939	1	2021-02-07 17:47:49.39091+00	test	\N	\N	https://gitlab.aweber.io/edeliv/Services/amp-kong
940	1	2021-02-07 17:47:49.460658+00	test	\N	\N	https://gitlab.aweber.io/edeliv/Services/edeliv-statsd
941	1	2021-02-07 17:47:49.532294+00	test	\N	\N	https://gitlab.aweber.io/edeliv/Services/meapi-varnish
942	1	2021-02-07 17:47:49.602499+00	test	\N	\N	https://gitlab.aweber.io/edeliv/Services/minio
943	1	2021-02-07 17:47:49.670273+00	test	\N	\N	https://gitlab.aweber.io/edeliv/Services/mock-account-notes
944	1	2021-02-07 17:47:49.754324+00	test	\N	\N	https://gitlab.aweber.io/edeliv/Services/mock-whoapi
945	1	2021-02-07 17:47:49.824864+00	test	\N	\N	https://gitlab.aweber.io/edeliv/Services/splash
946	1	2021-02-07 17:47:49.900396+00	test	\N	\N	https://gitlab.aweber.io/edeliv/Tools/application-creation-utils
947	1	2021-02-07 17:47:49.967549+00	test	\N	\N	https://gitlab.aweber.io/edeliv/Tools/aws-docs-sync
948	1	2021-02-07 17:47:50.036758+00	test	\N	\N	https://gitlab.aweber.io/edeliv/Tools/consumer-util
949	1	2021-02-07 17:47:50.113024+00	test	\N	\N	https://gitlab.aweber.io/edeliv/Tools/db-scripts
950	1	2021-02-07 17:47:50.180744+00	test	\N	\N	https://gitlab.aweber.io/edeliv/Tools/dedicated-ip
951	1	2021-02-07 17:47:50.25857+00	test	\N	\N	https://gitlab.aweber.io/edeliv/Tools/deliverability-utilities
952	1	2021-02-07 17:47:50.329284+00	test	\N	\N	https://gitlab.aweber.io/edeliv/Tools/dr-utilities
953	1	2021-02-07 17:47:50.399884+00	test	\N	\N	https://gitlab.aweber.io/edeliv/Tools/drdb-tools
954	1	2021-02-07 17:47:50.46533+00	test	\N	\N	https://gitlab.aweber.io/edeliv/Tools/edeliv-utilities
955	1	2021-02-07 17:47:50.538763+00	test	\N	\N	https://gitlab.aweber.io/edeliv/Tools/find-rewrite-accounts
956	1	2021-02-07 17:47:50.606159+00	test	\N	\N	https://gitlab.aweber.io/edeliv/Tools/graphite-metric-merging
957	1	2021-02-07 17:47:50.675612+00	test	\N	\N	https://gitlab.aweber.io/edeliv/Tools/jenkins-job-runner
958	1	2021-02-07 17:47:50.755077+00	test	\N	\N	https://gitlab.aweber.io/edeliv/Tools/momentum-util
959	1	2021-02-07 17:47:50.827098+00	test	\N	\N	https://gitlab.aweber.io/edeliv/Tools/nagios-check-status-report
960	2	2021-02-07 17:47:50.90573+00	test	\N	\N	https://grafana.aweber.io/d/-bnRnqQiz/momentum-dashboard?orgId=1&refresh=5m
961	1	2021-02-07 17:47:51.046573+00	test	\N	\N	https://gitlab.aweber.io/edeliv/Tools/queue-diverted-bc
962	1	2021-02-07 17:47:51.122056+00	test	\N	\N	https://gitlab.aweber.io/edeliv/Tools/rejected-node-assignments
963	1	2021-02-07 17:47:51.196561+00	test	\N	\N	https://gitlab.aweber.io/edeliv/Tools/smtp-echo-server
964	1	2021-02-07 17:47:51.270539+00	test	\N	\N	https://gitlab.aweber.io/Mobile/services/appstore-verifier
964	5	2021-02-07 17:47:51.340563+00	test	\N	\N	https://sonarqube.aweber.io/dashboard?id=Mobile%3Aappstore_verifier
965	2	2021-02-07 17:47:51.409589+00	test	\N	\N	https://grafana.aweber.io/d/crVrr76Wk/integrations-public-api-aweber-auth?orgId=1&refresh=5m
966	1	2021-02-07 17:47:51.514345+00	test	\N	\N	https://gitlab.aweber.io/integrations/services/aweber-labs
967	1	2021-02-07 17:47:51.585109+00	test	\N	\N	https://gitlab.aweber.io/integrations/services/aweber-labs
968	2	2021-02-07 17:47:51.65267+00	test	\N	\N	https://grafana.aweber.io/d/1F6DpKEZz/batch-sender
968	1	2021-02-07 17:47:51.683788+00	test	\N	\N	https://gitlab.aweber.io/integrations/services/batch-sender
968	4	2021-02-07 17:47:51.720782+00	test	\N	\N	https://sentry.io/organizations/aweber-communications/issues/?project=1877895
968	5	2021-02-07 17:47:51.764635+00	test	\N	\N	https://sonarqube.aweber.io/dashboard?id=int%3Abatchsender
969	2	2021-02-07 17:47:51.837255+00	test	\N	\N	https://grafana.aweber.io/d/av0sXgEZk/callback-batching-service?orgId=1
969	1	2021-02-07 17:47:51.873636+00	test	\N	\N	https://gitlab.aweber.io/integrations/services/callback-batching
969	4	2021-02-07 17:47:51.909647+00	test	\N	\N	https://sentry.io/organizations/aweber-communications/issues/?project=1872861
969	5	2021-02-07 17:47:51.94235+00	test	\N	\N	https://sonarqube.aweber.io/dashboard?id=int%3Acallbackbatching
970	1	2021-02-07 17:47:52.015007+00	test	\N	\N	https://gitlab.aweber.io/integrations/applications/check-rate-limit
970	5	2021-02-07 17:47:52.045292+00	test	\N	\N	https://sonarqube.aweber.io/dashboard?id=int%3Acheck-rate-limit
971	1	2021-02-07 17:47:52.118036+00	test	\N	\N	https://gitlab.aweber.io/Mobile/services/core-api/awfollowups
972	1	2021-02-07 17:47:52.195578+00	test	\N	\N	https://gitlab.aweber.io/integrations/libraries/core-models
973	2	2021-02-07 17:47:52.264141+00	test	\N	\N	https://grafana.aweber.io/d/V4avElkZz/integrations-cp-auth
973	1	2021-02-07 17:47:52.299421+00	test	\N	\N	https://gitlab.aweber.io/integrations/services/cp-auth
973	4	2021-02-07 17:47:52.331747+00	test	\N	\N	https://sentry.io/organizations/aweber-communications/issues/?project=1404939
973	5	2021-02-07 17:47:52.363603+00	test	\N	\N	https://sonarqube.aweber.io/dashboard?id=integrations%3Acp-auth
974	1	2021-02-07 17:47:52.435805+00	test	\N	\N	https://gitlab.aweber.io/integrations/applications/facebook-canvas
975	2	2021-02-07 17:47:52.506436+00	test	\N	\N	https://grafana.aweber.io/d/000000387/integrations-facebook-twitter-consumer
975	1	2021-02-07 17:47:52.541157+00	test	\N	\N	https://gitlab.aweber.io/integrations/consumers/fbtwitterconsumer
975	4	2021-02-07 17:47:52.571908+00	test	\N	\N	https://sentry.io/organizations/aweber-communications/issues/?project=205591
976	1	2021-02-07 17:47:52.639339+00	test	\N	\N	https://gitlab.aweber.io/integrations/applications/gotowebinar-client
976	4	2021-02-07 17:47:52.673193+00	test	\N	\N	https://sentry.io/organizations/aweber-communications/issues/?project=1255742
977	1	2021-02-07 17:47:52.740412+00	test	\N	\N	https://gitlab.aweber.io/integrations/applications/gotowebinar-common
977	5	2021-02-07 17:47:52.779794+00	test	\N	\N	https://sonarqube.aweber.io/dashboard?id=integrations%3Agotowebinar-common
978	2	2021-02-07 17:47:52.855491+00	test	\N	\N	https://grafana.aweber.io/d/-FEFcnOiz/gotowebinar-consumers?orgId=1&refresh=5m
978	1	2021-02-07 17:47:52.896074+00	test	\N	\N	https://gitlab.aweber.io/integrations/applications/gotowebinar-consumers
978	4	2021-02-07 17:47:52.933291+00	test	\N	\N	https://sentry.io/organizations/aweber-communications/issues/?project=1250651
978	5	2021-02-07 17:47:52.966799+00	test	\N	\N	https://sonarqube.aweber.io/dashboard?id=integrations%3Agotowebinar-consumer
979	1	2021-02-07 17:47:53.037603+00	test	\N	\N	https://gitlab.aweber.io/integrations/applications/gotowebinar-cron
979	5	2021-02-07 17:47:53.109073+00	test	\N	\N	https://sonarqube.aweber.io/dashboard?id=int%3Agotowebinar-cron
980	1	2021-02-07 17:47:53.176875+00	test	\N	\N	https://gitlab.aweber.io/integrations/applications/integrations-hub
981	4	2021-02-07 17:47:53.330361+00	test	\N	\N	https://sentry.io/organizations/aweber-communications/issues/?project=5495344
982	2	2021-02-07 17:47:53.401784+00	test	\N	\N	https://grafana.aweber.io/d/000000559/integrations-paypal?orgId=1
982	4	2021-02-07 17:47:53.468132+00	test	\N	\N	https://sentry.io/organizations/aweber-communications/issues/?project=1201206
983	2	2021-02-07 17:47:53.535412+00	test	\N	\N	https://grafana.aweber.io/d/-pzRL42Wz/labs-application-service
983	4	2021-02-07 17:47:53.602625+00	test	\N	\N	https://sentry.io/organizations/aweber-communications/issues/?project=1766017
984	5	2021-02-07 17:47:53.739411+00	test	\N	\N	https://sonarqube.aweber.io/dashboard?id=integrations%3Alabs-cleanup
985	2	2021-02-07 17:47:53.814391+00	test	\N	\N	https://grafana.aweber.io/d/000000488/mobstatpush-consumer?orgId=1
985	4	2021-02-07 17:47:53.88458+00	test	\N	\N	https://sentry.io/organizations/aweber-communications/issues/?project=230911
986	2	2021-02-07 17:47:53.953958+00	test	\N	\N	https://grafana.aweber.io/d/TVbMYRZZz/oauth2revoke-service
986	4	2021-02-07 17:47:54.029418+00	test	\N	\N	https://sentry.io/organizations/aweber-communications/issues/?project=1430456
987	4	2021-02-07 17:47:54.172961+00	test	\N	\N	https://sentry.io/organizations/aweber-communications/issues/?project=1763135
989	1	2021-02-07 17:47:54.385988+00	test	\N	\N	https://gitlab.aweber.io/integrations/applications/oauth2login
989	5	2021-02-07 17:47:54.45474+00	test	\N	\N	https://sonarqube.aweber.io/dashboard?id=integrations%3Aoauth2login
990	2	2021-02-07 17:47:54.524467+00	test	\N	\N	https://grafana.aweber.io/d/000000081/integrations-papi
990	4	2021-02-07 17:47:54.595744+00	test	\N	\N	https://sentry.io/organizations/aweber-communications/issues/?project=41993
991	1	2021-02-07 17:47:54.735138+00	test	\N	\N	https://gitlab.aweber.io/integrations/services/paypal-ipn-processor
992	2	2021-02-07 17:47:54.802448+00	test	\N	\N	https://grafana.aweber.io/d/paypal-ipn-service/integrations-paypal-ipn-service?orgId=1&refresh=5m
992	4	2021-02-07 17:47:54.876005+00	test	\N	\N	https://sentry.io/organizations/aweber-communications/issues/?project=5544890
993	1	2021-02-07 17:47:55.022306+00	test	\N	\N	https://gitlab.aweber.io/integrations/publicapi/public-api
994	2	2021-02-07 17:47:55.095524+00	test	\N	\N	https://grafana.aweber.io/d/000000522/integrations-publicapi-account?orgId=1
994	5	2021-02-07 17:47:55.173358+00	test	\N	\N	https://sonarqube.aweber.io/dashboard?id=integrations%3Apublicapi-account
995	2	2021-02-07 17:47:55.242338+00	test	\N	\N	https://grafana.aweber.io/d/rR0A1-NMk/integrations-publicapi-publicapi-broadcast
995	4	2021-02-07 17:47:55.316622+00	test	\N	\N	https://sentry.io/organizations/aweber-communications/issues/?project=5403015
996	1	2021-02-07 17:47:55.456155+00	test	\N	\N	https://gitlab.aweber.io/integrations/services/publicapi-custom-field/
996	5	2021-02-07 17:47:55.521054+00	test	\N	\N	https://sonarqube.aweber.io/dashboard?id=int%3Apublicapi-custom-field
997	2	2021-02-07 17:47:55.588366+00	test	\N	\N	https://grafana.aweber.io/d/-NZxnKYik/public-api-papi-image-service
997	4	2021-02-07 17:47:55.655352+00	test	\N	\N	https://sentry.io/organizations/aweber-communications/issues/?project=1338144
998	2	2021-02-07 17:47:55.724252+00	test	\N	\N	https://grafana.aweber.io/d/-tnUPhzMz/integrations-publicapi-integration
998	4	2021-02-07 17:47:55.797735+00	test	\N	\N	https://sentry.io/organizations/aweber-communications/issues/?project=5238136
999	1	2021-02-07 17:47:55.944445+00	test	\N	\N	https://gitlab.aweber.io/integrations/services/publicapi-landing-page
999	5	2021-02-07 17:47:56.010357+00	test	\N	\N	https://sonarqube.aweber.io/dashboard?id=int%3Alandingpage
1000	2	2021-02-07 17:47:56.086465+00	test	\N	\N	https://grafana.aweber.io/d/000000531/integrations-publicapi-list
1000	5	2021-02-07 17:47:56.161036+00	test	\N	\N	https://sonarqube.aweber.io/dashboard?id=int%3Apublicapi-list
1001	2	2021-02-07 17:47:56.22987+00	test	\N	\N	https://grafana.aweber.io/d/EdNa_yiMk/integrations-publicapi-webform
1001	4	2021-02-07 17:47:56.296488+00	test	\N	\N	https://sentry.io/organizations/aweber-communications/issues/?project=5274856
1003	1	2021-02-07 17:47:56.501745+00	test	\N	\N	https://gitlab.aweber.io/Mobile/services/pushconfig
1003	5	2021-02-07 17:47:56.570806+00	test	\N	\N	https://sonarqube.aweber.io/dashboard?id=Mobile%3Apushconfig
1004	2	2021-02-07 17:47:56.643693+00	test	\N	\N	https://grafana.aweber.io/d/000000452/pushnotifier-consumer?orgId=1
1004	4	2021-02-07 17:47:56.723753+00	test	\N	\N	https://sentry.io/organizations/aweber-communications/issues/?project=209374
1007	1	2021-02-07 17:47:57.014751+00	test	\N	\N	https://gitlab.aweber.io/integrations/applications/shopify-checkout-poller
1007	5	2021-02-07 17:47:57.085757+00	test	\N	\N	https://sonarqube.aweber.io/dashboard?id=int%3Aabandonedcheckouts
1008	2	2021-02-07 17:47:57.161377+00	test	\N	\N	https://grafana.aweber.io/d/rc9dSMJGz/integrations-shopify-webhook-processor
1008	4	2021-02-07 17:47:57.230114+00	test	\N	\N	https://sentry.io/organizations/aweber-communications/issues/?project=5544058&environment=production
1009	1	2021-02-07 17:47:57.373537+00	test	\N	\N	https://gitlab.aweber.io/integrations/services/subscriber-throttling
1009	5	2021-02-07 17:47:57.443915+00	test	\N	\N	https://sonarqube.aweber.io/dashboard?id=int%3Asubscriber-throttling
1010	2	2021-02-07 17:47:57.516+00	test	\N	\N	https://grafana.aweber.io/d/000000518/integrations-subscriptionqueueprocessor
1011	1	2021-02-07 17:47:57.652924+00	test	\N	\N	https://gitlab.aweber.io/Mobile/services/voyager
1011	5	2021-02-07 17:47:57.719659+00	test	\N	\N	https://sonarqube.aweber.io/dashboard?id=Mobile%3Avoyager
1012	2	2021-02-07 17:47:57.799357+00	test	\N	\N	https://grafana.aweber.io/d/000000377/integrations-wasp?orgId=1&refresh=30s
1013	1	2021-02-07 17:47:57.942469+00	test	\N	\N	https://gitlab.aweber.io/integrations/services/webhooks-add-subscriber-processor
1014	2	2021-02-07 17:47:58.008809+00	test	\N	\N	https://grafana.aweber.io/d/xlfskv8Wz/webhook-listening-consumers
1014	4	2021-02-07 17:47:58.074526+00	test	\N	\N	https://sentry.io/organizations/aweber-communications/issues/?project=1880295
1015	1	2021-02-07 17:47:58.220949+00	test	\N	\N	https://gitlab.aweber.io/integrations/consumers/webhooks-sender
1015	5	2021-02-07 17:47:58.296097+00	test	\N	\N	https://sonarqube.aweber.io/dashboard?id=int%3Awebhooks-sender
1016	1	2021-02-07 17:47:58.365792+00	test	\N	\N	https://gitlab.aweber.io/integrations/applications/weeblyapp
1021	1	2021-02-07 17:47:58.788082+00	test	\N	\N	https://gitlab.aweber.io/PSE/Applications/anabroker
1021	5	2021-02-07 17:47:58.858127+00	test	\N	\N	https://sonarqube.aweber.io/dashboard?id=pse%3Aanabroker
1022	2	2021-02-07 17:47:58.932554+00	test	\N	\N	https://grafana.aweber.io/d/000000229/analytics-processing?orgId=1
1022	4	2021-02-07 17:47:59.002122+00	test	\N	\N	https://sentry.io/organizations/aweber-communications/issues/?project=103966
1023	1	2021-02-07 17:47:59.150417+00	test	\N	\N	https://gitlab.aweber.io/PSE/Applications/aircall
1023	5	2021-02-07 17:47:59.220551+00	test	\N	\N	https://sonarqube.aweber.io/dashboard?id=pse%3Aaircall
1024	2	2021-02-07 17:47:59.29914+00	test	\N	\N	https://grafana.aweber.io/d/Hz-0C8pmk/admin-app?orgId=1&refresh=10s
1024	4	2021-02-07 17:47:59.371966+00	test	\N	\N	https://sentry.io/organizations/aweber-communications/issues/?project=207391
979	4	2021-02-07 17:47:53.071735+00	test	\N	\N	https://sentry.io/organizations/aweber-communications/issues/?project=1246473
980	4	2021-02-07 17:47:53.215248+00	test	\N	\N	https://sentry.io/organizations/aweber-communications/issues/?project=5174552
981	1	2021-02-07 17:47:53.294519+00	test	\N	\N	https://gitlab.aweber.io/integrations/applications/integrations-platform-client
982	1	2021-02-07 17:47:53.435742+00	test	\N	\N	https://gitlab.aweber.io/integrations/services/integrations
983	1	2021-02-07 17:47:53.567081+00	test	\N	\N	https://gitlab.aweber.io/integrations/services/labs-application
983	5	2021-02-07 17:47:53.635878+00	test	\N	\N	https://sonarqube.aweber.io/dashboard?id=int%3Alabs-application
984	1	2021-02-07 17:47:53.705407+00	test	\N	\N	https://gitlab.aweber.io/integrations/applications/labs-cleanup
985	1	2021-02-07 17:47:53.847473+00	test	\N	\N	https://gitlab.aweber.io/Mobile/consumers/mobstatpush
986	1	2021-02-07 17:47:53.989651+00	test	\N	\N	https://gitlab.aweber.io/integrations/services/oauth2revoke
986	5	2021-02-07 17:47:54.064521+00	test	\N	\N	https://sonarqube.aweber.io/dashboard?id=integrations%3Aoauth2revoke
987	1	2021-02-07 17:47:54.140505+00	test	\N	\N	https://gitlab.aweber.io/Mobile/consumers/oauth2-user-revoker
987	5	2021-02-07 17:47:54.206853+00	test	\N	\N	https://sonarqube.aweber.io/dashboard?id=Mobile%3Aoauth2-user-revoker
988	1	2021-02-07 17:47:54.283312+00	test	\N	\N	https://gitlab.aweber.io/integrations/libraries/oauth-middleware
989	2	2021-02-07 17:47:54.353552+00	test	\N	\N	https://grafana.aweber.io/d/gAR4RXgZz/oauth2login-service
989	4	2021-02-07 17:47:54.421788+00	test	\N	\N	https://sentry.io/organizations/aweber-communications/issues/?project=1429392
990	1	2021-02-07 17:47:54.558591+00	test	\N	\N	https://gitlab.aweber.io/integrations/services/papi
990	5	2021-02-07 17:47:54.631227+00	test	\N	\N	https://sonarqube.aweber.io/dashboard?id=int%3Apapi
991	2	2021-02-07 17:47:54.700826+00	test	\N	\N	https://grafana.aweber.io/d/000000559/integrations-paypal
992	1	2021-02-07 17:47:54.83566+00	test	\N	\N	https://gitlab.aweber.io/integrations/services/paypal-ipn-service
992	5	2021-02-07 17:47:54.918842+00	test	\N	\N	https://sonarqube.aweber.io/dashboard?id=int%3Apaypal-ipn-service
993	2	2021-02-07 17:47:54.986934+00	test	\N	\N	https://grafana.aweber.io/d/000000309/integrations-public-api-call-counts?orgId=1
994	1	2021-02-07 17:47:55.137806+00	test	\N	\N	https://gitlab.aweber.io/integrations/publicapi/account
995	1	2021-02-07 17:47:55.282416+00	test	\N	\N	https://gitlab.aweber.io/integrations/services/publicapi-broadcast
995	5	2021-02-07 17:47:55.351574+00	test	\N	\N	https://sonarqube.aweber.io/dashboard?id=int%3Apublicapi-broadcast
996	2	2021-02-07 17:47:55.420675+00	test	\N	\N	https://grafana.aweber.io/d/sJKicyIMk/integrations-publicapi-publicapi-custom-field
996	4	2021-02-07 17:47:55.486999+00	test	\N	\N	https://sentry.io/organizations/aweber-communications/issues/?project=5389708
997	1	2021-02-07 17:47:55.621541+00	test	\N	\N	https://gitlab.aweber.io/integrations/services/publicapi-image
998	1	2021-02-07 17:47:55.763632+00	test	\N	\N	https://gitlab.aweber.io/integrations/services/publicapi-integration
998	5	2021-02-07 17:47:55.83342+00	test	\N	\N	https://sonarqube.aweber.io/dashboard?id=int%3Apublicapiintegration
999	2	2021-02-07 17:47:55.907875+00	test	\N	\N	https://grafana.aweber.io/d/ZNifhhzMz/integrations-publicapi-landing-pages
999	4	2021-02-07 17:47:55.976366+00	test	\N	\N	https://sentry.io/organizations/aweber-communications/issues/?project=5241025
1000	1	2021-02-07 17:47:56.125517+00	test	\N	\N	https://gitlab.aweber.io/integrations/services/publicapi-list
1001	1	2021-02-07 17:47:56.263026+00	test	\N	\N	https://gitlab.aweber.io/integrations/services/publicapi-webform/
1001	5	2021-02-07 17:47:56.332056+00	test	\N	\N	https://sonarqube.aweber.io/dashboard?id=int%3Apublicapi-webform
1002	1	2021-02-07 17:47:56.398727+00	test	\N	\N	https://gitlab.aweber.io/integrations/libraries/publicapi-auth-mixin
1003	2	2021-02-07 17:47:56.470262+00	test	\N	\N	https://grafana.aweber.io/d/000000429/pushconfig-service?orgId=1
1003	4	2021-02-07 17:47:56.537674+00	test	\N	\N	https://sentry.io/organizations/aweber-communications/issues/?project=185260
1004	1	2021-02-07 17:47:56.679565+00	test	\N	\N	https://gitlab.aweber.io/Mobile/consumers/pushnotifier
1004	5	2021-02-07 17:47:56.763794+00	test	\N	\N	https://sonarqube.aweber.io/dashboard?id=Mobile%3Apushnotifier
1005	1	2021-02-07 17:47:56.832922+00	test	\N	\N	https://gitlab.aweber.io/integrations/libraries/python-core-models
1006	1	2021-02-07 17:47:56.907699+00	test	\N	\N	https://gitlab.aweber.io/integrations/libraries/python-jwt-lucid
1007	2	2021-02-07 17:47:56.981859+00	test	\N	\N	https://grafana.aweber.io/d/k6omwusZk/integrations-shopify-checkout-poller?orgId=1
1007	4	2021-02-07 17:47:57.048448+00	test	\N	\N	https://sentry.io/organizations/aweber-communications/issues/?project=1890347
1008	1	2021-02-07 17:47:57.193912+00	test	\N	\N	https://gitlab.aweber.io/integrations/services/shopify-webhook-processor
1008	5	2021-02-07 17:47:57.265002+00	test	\N	\N	https://sonarqube.aweber.io/dashboard?id=int%3Ashopifywebhookprocessor
1009	2	2021-02-07 17:47:57.339804+00	test	\N	\N	https://grafana.aweber.io/d/UtUp7EnWz/addsubscribers-blocked-emails?orgId=1&refresh=5m
1009	4	2021-02-07 17:47:57.407469+00	test	\N	\N	https://sentry.io/organizations/aweber-communications/issues/?project=1506371
1010	1	2021-02-07 17:47:57.55244+00	test	\N	\N	https://gitlab.aweber.io/integrations/services/subscriptionqueueprocessor
1011	2	2021-02-07 17:47:57.61875+00	test	\N	\N	https://grafana.aweber.io/d/000000072/voyager-service
1011	4	2021-02-07 17:47:57.685515+00	test	\N	\N	https://sentry.io/organizations/aweber-communications/issues/?project=60217
1012	1	2021-02-07 17:47:57.834078+00	test	\N	\N	https://gitlab.aweber.io/integrations/services/webhooks-add-subscriber-processor
1013	2	2021-02-07 17:47:57.906359+00	test	\N	\N	https://grafana.aweber.io/d/000000377/integrations-wasp?orgId=1&refresh=30s
1014	1	2021-02-07 17:47:58.042631+00	test	\N	\N	https://gitlab.aweber.io/integrations/consumers/webhooks-listener
1014	5	2021-02-07 17:47:58.111286+00	test	\N	\N	https://sonarqube.aweber.io/dashboard?id=int%3Awebhooks-listener
1015	2	2021-02-07 17:47:58.188001+00	test	\N	\N	https://grafana.aweber.io/d/RUe5wC9Zk/webhooks-send-consumers
1015	4	2021-02-07 17:47:58.262888+00	test	\N	\N	https://sentry.io/organizations/aweber-communications/issues/?project=4179756
1016	4	2021-02-07 17:47:58.396495+00	test	\N	\N	https://sentry.io/organizations/aweber-communications/issues/?project=1820802
1017	1	2021-02-07 17:47:58.467118+00	test	\N	\N	https://gitlab.aweber.io/integrations/applications/weeblyelement
1018	1	2021-02-07 17:47:58.535643+00	test	\N	\N	https://gitlab.aweber.io/integrations/applications/wordpress-webform-widget
1019	1	2021-02-07 17:47:58.602996+00	test	\N	\N	https://gitlab.aweber.io/unmigrated/zendesk-widget
1020	1	2021-02-07 17:47:58.671787+00	test	\N	\N	https://gitlab.aweber.io/BoFs/FE/libraries/aweberjs
1021	2	2021-02-07 17:47:58.753494+00	test	\N	\N	https://grafana.aweber.io/d/9BFEDX9iz/anabroker-service?orgId=1
1021	4	2021-02-07 17:47:58.822107+00	test	\N	\N	https://sentry.io/organizations/aweber-communications/issues/?project=1132504
1022	1	2021-02-07 17:47:58.966924+00	test	\N	\N	https://gitlab.aweber.io/PSE/Applications/anadb-consumers
1022	5	2021-02-07 17:47:59.037383+00	test	\N	\N	https://sonarqube.aweber.io/dashboard?id=pse%3Aanadb-consumers
1023	2	2021-02-07 17:47:59.112765+00	test	\N	\N	https://grafana.aweber.io/d/oZSg6XhGk/aircall-integration-service?orgId=1&refresh=30s
1023	4	2021-02-07 17:47:59.186254+00	test	\N	\N	https://sentry.io/organizations/aweber-communications/issues/?project=5496429
1026	1	2021-02-07 17:47:59.508458+00	test	\N	\N	https://gitlab.aweber.io/PSE/Applications/admin-v2
1027	2	2021-02-07 17:47:59.578535+00	test	\N	\N	https://grafana.aweber.io/d/LkiOL6riz/phoneautomation-scheduler?orgId=1
1027	4	2021-02-07 17:47:59.649446+00	test	\N	\N	https://sentry.io/organizations/aweber-communications/issues/?project=1406152
1028	2	2021-02-07 17:47:59.726122+00	test	\N	\N	https://grafana.aweber.io/d/Rsn1gRCiz/phoneautomation-dialer?orgId=1
1028	4	2021-02-07 17:47:59.798348+00	test	\N	\N	https://sentry.io/organizations/aweber-communications/issues/?project=1406151
1029	2	2021-02-07 17:47:59.874197+00	test	\N	\N	https://grafana.aweber.io/d/V0K3QKrik/phoneautomation-api?orgId=1
1029	4	2021-02-07 17:47:59.943803+00	test	\N	\N	https://sentry.io/organizations/aweber-communications/issues/?project=1403311
1030	2	2021-02-07 17:48:00.013061+00	test	\N	\N	https://grafana.aweber.io/d/4F6F3bNZz/invoice-status-consumer?orgId=1
1030	4	2021-02-07 17:48:00.084061+00	test	\N	\N	https://sentry.io/organizations/aweber-communications/issues/?project=1553306
1031	1	2021-02-07 17:48:00.159901+00	test	\N	\N	https://gitlab.aweber.io/PSE/Applications/imbi
1032	1	2021-02-07 17:48:00.226071+00	test	\N	\N	https://gitlab.aweber.io/PSE/Applications/imbi
1033	1	2021-02-07 17:48:00.298308+00	test	\N	\N	https://gitlab.aweber.io/PSE/Applications/zendesk-account-bot
1034	2	2021-02-07 17:48:00.372334+00	test	\N	\N	https://grafana.aweber.io/d/CgyuVUtGz/analytics-ingestion?orgId=1
1034	4	2021-02-07 17:48:00.441334+00	test	\N	\N	https://sentry.io/organizations/aweber-communications/issues/?project=5408336
1036	1	2021-02-07 17:48:00.646944+00	test	\N	\N	https://gitlab.aweber.io/PSE/Applications/rollup
1036	5	2021-02-07 17:48:00.717161+00	test	\N	\N	https://sonarqube.aweber.io/dashboard?id=pse%3Arollup
1037	1	2021-02-07 17:48:00.800845+00	test	\N	\N	https://gitlab.aweber.io/PSE/Applications/rollup-distributor
1037	5	2021-02-07 17:48:00.87936+00	test	\N	\N	https://sonarqube.aweber.io/dashboard?id=pse%3Arollup-distributor
1038	2	2021-02-07 17:48:00.970072+00	test	\N	\N	https://grafana.aweber.io/d/-EzwFwKik/transmogrifier?orgId=1&refresh=1m
1038	4	2021-02-07 17:48:01.046402+00	test	\N	\N	https://sentry.io/organizations/aweber-communications/issues/?project=1252537
1039	1	2021-02-07 17:48:01.219063+00	test	\N	\N	https://gitlab.aweber.io/PSE/Applications/firehydrant
1039	5	2021-02-07 17:48:01.29767+00	test	\N	\N	https://sonarqube.aweber.io/dashboard?id=pse%3Afirehydrant
1027	1	2021-02-07 17:47:59.61197+00	test	\N	\N	https://gitlab.aweber.io/PSE/Applications/phone-automation
1028	1	2021-02-07 17:47:59.765691+00	test	\N	\N	https://gitlab.aweber.io/PSE/Applications/phone-automation
1029	1	2021-02-07 17:47:59.910055+00	test	\N	\N	https://gitlab.aweber.io/PSE/Applications/phoneautomation
1030	1	2021-02-07 17:48:00.049132+00	test	\N	\N	https://gitlab.aweber.io/PSE/Applications/invoice-status-change-consumer
1034	1	2021-02-07 17:48:00.404769+00	test	\N	\N	https://gitlab.aweber.io/PSE/Applications/analytics-ingestion
1034	5	2021-02-07 17:48:00.476143+00	test	\N	\N	https://sonarqube.aweber.io/dashboard?id=pse%3Aanalytics-ingestion
1035	1	2021-02-07 17:48:00.544296+00	test	\N	\N	https://gitlab.aweber.io/PSE/Applications/yodawg
1036	2	2021-02-07 17:48:00.611833+00	test	\N	\N	https://grafana.aweber.io/d/000000245/rollup-service?orgId=1&refresh=1m
1036	4	2021-02-07 17:48:00.680245+00	test	\N	\N	https://sentry.io/organizations/aweber-communications/issues/?project=64297
1037	4	2021-02-07 17:48:00.836831+00	test	\N	\N	https://sentry.io/organizations/aweber-communications/issues/?project=1258078
1038	1	2021-02-07 17:48:01.009696+00	test	\N	\N	https://gitlab.aweber.io/PSE/Applications/transmogrifier
1038	5	2021-02-07 17:48:01.091712+00	test	\N	\N	https://sonarqube.aweber.io/dashboard?id=pse%3Atransmogrifier
1039	2	2021-02-07 17:48:01.180342+00	test	\N	\N	https://grafana.aweber.io/d/000000285/firehydrant-consumers?orgId=1
1039	4	2021-02-07 17:48:01.263367+00	test	\N	\N	https://sentry.io/organizations/aweber-communications/issues/?project=80384
\.


--
-- Name: namespaces_id_seq; Type: SEQUENCE SET; Schema: v1; Owner: postgres
--

SELECT pg_catalog.setval('v1.namespaces_id_seq', 10, true);


--
-- Name: project_fact_type_options_id_seq; Type: SEQUENCE SET; Schema: v1; Owner: postgres
--

SELECT pg_catalog.setval('v1.project_fact_type_options_id_seq', 1, false);


--
-- Name: project_fact_types_id_seq; Type: SEQUENCE SET; Schema: v1; Owner: postgres
--

SELECT pg_catalog.setval('v1.project_fact_types_id_seq', 2, true);


--
-- Name: project_link_types_id_seq; Type: SEQUENCE SET; Schema: v1; Owner: postgres
--

SELECT pg_catalog.setval('v1.project_link_types_id_seq', 5, true);


--
-- Name: project_types_id_seq; Type: SEQUENCE SET; Schema: v1; Owner: postgres
--

SELECT pg_catalog.setval('v1.project_types_id_seq', 12, true);


--
-- Name: projects_id_seq; Type: SEQUENCE SET; Schema: v1; Owner: postgres
--

SELECT pg_catalog.setval('v1.projects_id_seq', 1039, true);


--
-- PostgreSQL database dump complete
--

