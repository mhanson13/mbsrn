import AdminPageContent from "../admin/AdminPageContent";

// Compatibility route: keep /users bookmarks working while /user-mgmt is canonical.
export default function UsersCompatibilityPage() {
  return <AdminPageContent mode="all" />;
}
