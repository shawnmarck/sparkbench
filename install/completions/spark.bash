# bash completion for spark — source or install to /etc/bash_completion.d/spark
_spark() {
  local cur prev words cword
  COMPREPLY=()
  cur="${COMP_WORDS[COMP_CWORD]}"
  prev="${COMP_WORDS[COMP_CWORD-1]}"

  local groups="status inference recipe models shelf engine gpu hf help -h --help"

  if [[ ${COMP_CWORD} -eq 1 ]]; then
    COMPREPLY=( $(compgen -W "${groups}" -- "${cur}") )
    return 0
  fi

  case "${COMP_WORDS[1]}" in
    inference)
      if [[ ${COMP_CWORD} -eq 2 ]]; then
        COMPREPLY=( $(compgen -W "list status up down logs bench" -- "${cur}") )
      fi
      ;;
    recipe)
      if [[ ${COMP_CWORD} -eq 2 ]]; then
        COMPREPLY=( $(compgen -W "list scaffold testing promote discard" -- "${cur}") )
      fi
      ;;
    models)
      if [[ ${COMP_CWORD} -eq 2 ]]; then
        COMPREPLY=( $(compgen -W "verify removal inventory" -- "${cur}") )
      elif [[ ${COMP_CWORD} -eq 3 && "${prev}" == verify ]]; then
        COMPREPLY=( $(compgen -W "get set list pending" -- "${cur}") )
      fi
      ;;
    shelf)
      if [[ ${COMP_CWORD} -eq 2 ]]; then
        COMPREPLY=( $(compgen -W "pull push rm status" -- "${cur}") )
      fi
      ;;
    engine)
      if [[ ${COMP_CWORD} -eq 2 ]]; then
        COMPREPLY=( $(compgen -W "eugr llama" -- "${cur}") )
      elif [[ ${COMP_CWORD} -eq 3 ]]; then
        if [[ "${prev}" == eugr ]]; then
          COMPREPLY=( $(compgen -W "up down logs status build" -- "${cur}") )
        else
          COMPREPLY=( $(compgen -W "up down logs status" -- "${cur}") )
        fi
      fi
      ;;
    hf)
      if [[ ${COMP_CWORD} -eq 2 ]]; then
        COMPREPLY=( $(compgen -W "login" -- "${cur}") )
      fi
      ;;
  esac
}

complete -F _spark spark