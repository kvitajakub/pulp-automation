Name:		pulp_auto
Version:	0.7
Release:	1%{?dist}
Summary:	Pulp REST API automation library and test cases

Group:		Development/Tools
License:	GPLv3+
URL:		https://github.com/RedHatQE/pulp-automation
Source0:	%{name}-%{version}.tar.gz
BuildArch:  	noarch

BuildRequires:	python-devel
Requires:	python-nose, python-gevent, python-qpid, PyYAML

%description
%{summary}

%prep
%setup -q

%build

%install
%{__python} setup.py install --single-version-externally-managed -O1 --root $RPM_BUILD_ROOT --record=INSTALLED_FILES

%clean
rm -rf $RPM_BUILD_ROOT

%files
%defattr(-,root,root,-)
%doc LICENSE README.md
%{python_sitelib}/*.egg-info
%{python_sitelib}/%{name}/*.py*
%dir %{_datadir}/%{name}/tests
%attr(0644, root, root) %{_datadir}/%{name}/tests/*.py
%exclude %{_datadir}/%name/tests/*.py?

%changelog
