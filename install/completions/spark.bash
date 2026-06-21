# bash completion for spark — prefix-aware at every level
# install to /etc/bash_completion.d/spark

_spark_profiles() {
  /opt/spark/scripts/spark inference list 2>/dev/null \
    | awk 'NR>2 && $1 !~ /^-+/ {print $1}'
}

_spark_recipes() {
  /opt/spark/scripts/spark recipe list 2>/dev/null \
    | awk 'NF {print $1}'
}

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
      elif [[ ${COMP_CWORD} -eq 3 && "${prev}" == up || ${COMP_CWORD} -eq 3 && "${prev}" == logs ]]; then
        COMPREPLY=( $(compgen -W "$(_spark_profiles)" -- "${cur}") )
      fi
      ;;
    recipe)
      if [[ ${COMP_CWORD} -eq 2 ]]; then
        COMPREPLY=( $(compgen -W "list scaffold testing promote discard" -- "${cur}") )
      elif [[ ${COMP_CWORD} -eq 3 && "${prev}" =~ ^(testing|promote|discard)$ ]]; then
        COMPREPLY=( $(compgen -W "$(_spark_recipes)" -- "${cur}") )
      elif [[ ${COMP_CWORD} -eq 4 && "${COMP_WORDS[2]}" == scaffold ]]; then
        COMPREPLY=( $(compgen -W "llamacpp eugr" -- "${cur}") )
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

complete -o bashdefault -o default -F _spark spark