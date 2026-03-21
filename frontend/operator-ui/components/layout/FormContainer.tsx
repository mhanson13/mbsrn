import type { FormHTMLAttributes, ReactNode } from "react";

type FormContainerProps = FormHTMLAttributes<HTMLFormElement> & {
  children: ReactNode;
};

export function FormContainer({ children, className = "", ...rest }: FormContainerProps) {
  const classes = className ? `form-container ${className}` : "form-container";
  return (
    <form className={classes} {...rest}>
      {children}
    </form>
  );
}
